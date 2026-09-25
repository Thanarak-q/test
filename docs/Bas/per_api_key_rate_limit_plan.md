# Per-API-Key Rate Limit Plan

สถานะ: แผนออกแบบ standalone สำหรับ `perkey_rate_limit` ต่อจาก `validate_api_key`

## ขอบเขต

เอกสารนี้กำหนดเฉพาะส่วน `Per-API-Key Rate Limit` ใน `req.md` เท่านั้น

- ออกแบบและทดสอบ `perkey_rate_limit(user_id, est_tokens)`
- ใช้ `user_id` จากผลลัพธ์ของ `validate_api_key` เป็น input เท่านั้น
- ไม่รวม `estimate_tokens`, `read_rate_limit`, `model_validate` และ quota lifecycle
- ไม่แก้ `pre_auth_rate_limit` ซึ่งเป็น IP bucket คนละชั้นกัน
- ค่า capacity/refill ที่ใช้จริงต้องยืนยันเป็น policy ก่อนเปิดใช้งาน

### ความสัมพันธ์กับ quota

`rl:tok` และ `quota` เป็นกลไกคนละชั้น แม้ทั้งคู่จะคิดต้นทุนจาก token เหมือนกัน:

| กลไก     | ขอบเขตเวลา      | ที่เก็บ                | หน้าที่                        |
| -------- | --------------- | ---------------------- | ------------------------------ |
| `rl:tok` | ต่อนาที/ชั่วโมง | Redis ของ feature      | คุม burst และอัตราการใช้ token |
| `quota`  | ต่อเดือน        | quota state ของแอปหลัก | คุมยอด token สะสมตามโควตารวม   |

ดังนั้น `perkey_rate_limit` จะตรวจและหักเฉพาะ `rl:tok` แบบ atomic ร่วมกับ request bucket เท่านั้น ไม่อ่าน ไม่หัก และไม่ settle `quota`; การตรวจหรือ reserve quota เป็น boundary ถัดไปของ flow

สถานะปัจจุบันใน repo: ยังไม่มี service นี้ใน `api/app/services/` มีเพียง constants ใน `app/constants/llm.py`

## Contract

```text
perkey_rate_limit(redis, user_id, est_tokens)
    -> {allowed, remaining, reset, limit_type}
    | 413
    | 429
    | 503
```

ลำดับ boundary ที่อยู่นอก function นี้:

```text
validate_api_key
  -> reject unsupported params
  -> estimate_tokens
  -> perkey_rate_limit
  -> model_validate
```

function นี้ไม่รับ `Request` ไม่อ่าน header และไม่คำนวณ `est_tokens` เอง

## ข้อกำหนดที่ต้องรักษา

### Input

- `user_id` ต้องเป็น integer > 0 และไม่ใช่ `bool`
- `user_id` ต้องมาจาก authentication record เท่านั้น ห้ามอ่านจาก request/header/body
- `est_tokens` ต้องเป็น integer > 0 และไม่ใช่ `bool`
- `est_tokens = estimate_tokens(messages) + cap_tokens` คำนวณโดย caller
- `est_tokens` ใช้เป็น cost ของ `rl:tok` เฉพาะ rate limit ไม่ใช่ค่าที่นำไป settle `quota`
- `est_tokens > MAX_INPUT_TOKENS` ตอบ 413 ก่อนแตะ Redis

### Bucket

```text
rl:key:{user_id}   request count   cost = 1
rl:tok:{user_id}   token volume    cost = est_tokens
```

- ทั้งสอง bucket เป็น token bucket ที่ refill ตามเวลา
- refill ใช้ `redis.call('TIME')` ไม่ใช่นาฬิกาของ app
- แต่ละ bucket มี capacity, refill rate และ TTL ของตัวเอง
- key ต้องประกอบจาก `user_id` เท่านั้น ห้ามผสมค่าจาก request

### Atomicity

- ใช้ Lua script เดียวที่รับ 2 KEYS
- ตรวจทั้งสอง bucket ให้ครบก่อนหัก
- ผ่านทั้งคู่ -> หักทั้งคู่
- ไม่ผ่านอย่างน้อยหนึ่ง bucket -> ไม่หักเลย
- ห้ามแยกเป็นหลาย command จาก Python เพราะเปิดช่องให้ request อื่นแทรกระหว่างตรวจกับหัก

### Failure behavior

- Redis error/timeout/script error -> 503 และ fail closed
- ห้าม fallback ไป in-memory bucket หรือ app clock
- deny -> 429 พร้อม `RateLimit-*` และ `Retry-After`
- header ที่ส่งกลับใช้ค่าของ bucket ที่ปฏิเสธเท่านั้น
- `limit_type` มีค่า `request` หรือ `token`
- ถ้าไม่ผ่านทั้งคู่ ต้องมี precedence คงที่และทดสอบได้

## แผนดำเนินงาน

### Phase 1: กำหนด policy และ constants

กำหนดและยืนยันค่า:

- `request_capacity`, `request_refill`, `request_ttl`
- `token_capacity`, `token_refill`, `token_ttl`
- `MAX_INPUT_TOKENS`

เกณฑ์ผ่าน: ค่าที่ใช้ทั้งหมดอยู่ใน constants/config ไม่มี magic number ใน service

### Phase 2: เขียน Lua script

script ต้องทำตามลำดับ:

1. อ่านเวลาจาก `redis.call('TIME')`
2. refill ทั้งสอง bucket
3. ตรวจ request bucket และ token bucket
4. หักเมื่อผ่านทั้งคู่เท่านั้น
5. เขียน state และตั้ง TTL
6. คืน `allowed`, remaining, reset, retry และ `limit_type`

เกณฑ์ผ่าน: ไม่มีกรณีที่ bucket เดียวถูกหักโดยอีก bucket ไม่ผ่าน

### Phase 3: ประกอบ service

ลำดับภายใน `perkey_rate_limit`:

1. validate `user_id` และ `est_tokens`
2. ตรวจ `MAX_INPUT_TOKENS` และตอบ 413 ก่อนเรียก Redis
3. เรียก Lua script ด้วย 2 keys
4. แปลงผลลัพธ์เป็น result object
5. deny -> 429 พร้อม headers ของ bucket ที่ปฏิเสธ
6. Redis error -> 503

เกณฑ์ผ่าน: ไม่มี branch ที่ปล่อยผ่านเมื่อ Redis ใช้ไม่ได้

### Phase 4: เชื่อม boundary ที่อนุญาต

- ต้องเรียกหลัง `validate_api_key` และหลัง `estimate_tokens`
- ต้องเรียกก่อน `model_validate`, `quota_reserve` และ provider call
- ส่ง `RateLimit-*` headers ต่อให้ response ของ endpoint

## Test plan

ใช้ fake Redis สำหรับ unit test:

- ผ่านทั้งสอง bucket: หักทั้งคู่ และ keys เป็น `rl:key:{user_id}`, `rl:tok:{user_id}`
- request bucket ไม่พอ: 429 และ `limit_type=request`
- token bucket ไม่พอ: 429 และ `limit_type=token`
- ไม่ผ่านทั้งคู่: `limit_type` ตาม precedence ที่กำหนด
- bucket ใดไม่ผ่าน: ไม่มี bucket ใดถูกหัก
- `est_tokens > MAX_INPUT_TOKENS`: 413 และ Redis ไม่ถูกเรียก
- `user_id` เป็น 0, ติดลบ, `bool` หรือชนิดผิด: reject ก่อนแตะ Redis
- `est_tokens` เป็น 0, ติดลบ, `bool` หรือชนิดผิด: reject ก่อนแตะ Redis
- Redis error: 503 และไม่ fail open
- deny response มี `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, `Retry-After`
- cost ที่ส่งเข้า script ตรงกับ `est_tokens`

integration test กับ Redis จริง: ยิง concurrent requests แล้วยอดรวมที่ถูกหักต้องไม่เกิน capacity

## Implementation Checklist

### Contract และ input

- [ ] กำหนด public contract ของ `perkey_rate_limit` แล้ว
- [ ] service ไม่รับ `Request` และไม่อ่าน header
- [ ] validate `user_id` และ `est_tokens` ก่อนสร้าง key
- [ ] 413 เกิดก่อนการเรียก Redis ทุกกรณี

### Bucket และ atomicity

- [ ] ใช้ key `rl:key:{user_id}` และ `rl:tok:{user_id}`
- [ ] Lua script เดียวรับ 2 KEYS
- [ ] refill ด้วย `redis.call('TIME')`
- [ ] ตรวจทั้งสอง bucket ก่อนหัก
- [ ] ไม่ผ่าน -> ไม่หัก bucket ใดเลย
- [ ] ตั้ง TTL ของทั้งสอง key

### Response และ failure

- [ ] deny ตอบ 429 พร้อม headers ของ bucket ที่ปฏิเสธ
- [ ] คืน `limit_type` เป็น `request` หรือ `token`
- [ ] Redis failure ตอบ 503 และ fail closed
- [ ] ไม่มี fallback ไป local bucket

### Boundary และ tests

- [ ] เรียกหลัง `validate_api_key` และก่อน `model_validate`
- [ ] เรียกก่อน `quota_reserve` และ provider call
- [ ] unit tests ครบตาม test plan
- [ ] integration test ยืนยัน atomic ภายใต้ concurrency
- [ ] lint, type check และ test suite ผ่าน

## คำถามที่ต้องตัดสินใจก่อน implementation

1. ค่า capacity/refill ของ request bucket และ token bucket ใน production
2. precedence ของ `limit_type` เมื่อไม่ผ่านทั้งสอง bucket
3. error envelope ที่ใช้: `AppError` ที่มี domain prefix หรือ `HTTPException` ตามแบบ `pre_auth_rate_limit` ปัจจุบัน
4. TTL ของ bucket ที่เหมาะกับ traffic จริง
5. จะส่ง `RateLimit-*` headers ใน success response ด้วยหรือเฉพาะตอน deny

## Definition of done

- `perkey_rate_limit` ทำงานโดยพึ่ง `user_id`, `est_tokens` และ Redis เท่านั้น
- การตรวจและหักทั้งสอง bucket เป็น atomic operation เดียว
- request ที่ถูกปฏิเสธไม่ทำให้ bucket ใดถูกหัก
- `est_tokens` เกิน policy ถูกปฏิเสธก่อนแตะ Redis
- Redis failure ไม่ทำให้ request ผ่าน
- deny response มี `limit_type` และ headers ของ bucket ที่ปฏิเสธ
- rate limit เกิดก่อน model lookup, quota และ provider call
