# Validate API Key Plan

สถานะ: แผนออกแบบ standalone สำหรับ `validate_api_key` ต่อจาก `require_https` และ `pre_auth_rate_limit`

## ขอบเขต

เอกสารนี้กำหนดเฉพาะการตรวจ API key ตามส่วน `Validate API Key` ใน `req.md` เท่านั้น

- ออกแบบและทดสอบ `validate_api_key(token, source_ip)`
- ใช้ผลจาก `require_https` และ `pre_auth_rate_limit` เป็น boundary ก่อนหน้าเท่านั้น
- ไม่เรียกใช้ ไม่แก้ไข และไม่ผูกกับส่วนประกอบใดนอกขอบเขตการตรวจ API key นี้
- รายละเอียดในแผนเป็นข้อเสนอสำหรับ implementation ใหม่ทั้งหมด

## Contract

```text
validate_api_key(token, source_ip) -> {user_id, key_id} | 401 | 503
```

ลำดับ boundary ที่อยู่นอก function นี้:

```text
require_https
  -> pre_auth_rate_limit
  -> validate_api_key
```

`source_ip` ต้องเป็นค่าที่ผ่าน trusted-proxy handling จาก `pre_auth_rate_limit` แล้ว โดย function นี้ไม่อ่าน header และไม่คำนวณ IP เอง

## ข้อกำหนดที่ต้องรักษา

### Token parsing

รูปแบบ token ต้องเป็น:

```text
mthw01_{key_id}_{secret}
```

- prefix ต้องตรงกันและต้องมีสามส่วนเท่านั้น
- `key_id` ต้องเป็น ULID แบบ Crockford Base32 ยาว 26 ตัว
- `secret` ต้องเป็น base62 ยาว 32 ตัว
- token ผิดรูปทุกกรณีตอบ 401 ทันที
- token ผิดรูปต้องไม่แตะ Redis หรือ database
- raw token และ secret อยู่เฉพาะ local scope ของ function
- ห้ามใส่ token หรือ secret ใน result, exception, log, cache หรือ audit payload

### Authentication data

- คำนวณ `key_hash = SHA-256(secret)` เท่านั้น
- secret มี entropy สูงจาก CSPRNG จึงไม่ใช้ bcrypt หรือ argon2
- identity ที่คืนต้องมาจาก authentication record เท่านั้น
- ห้ามรับหรือสร้าง `user_id` จาก request, header, default หรือ fallback ใด ๆ
- status ที่ผ่านได้มีเพียง `active`
- เปรียบเทียบ hash ด้วย constant-time comparison

### Cache behavior

ใช้ key ตามรูปแบบนี้:

```text
auth:neg:{key_id}   TTL 30 seconds
auth:{key_id}       TTL 60 seconds
```

- ตรวจ negative cache ก่อน query database; hit แล้วตอบ 401
- negative cache ใช้เฉพาะกรณีไม่พบ `key_id`
- ห้าม cache negative จาก hash ผิดหรือ status ไม่ active
- positive cache ต้องมี `user_id`, `key_hash`, `status`
- positive cache field ไม่ครบ, parse ไม่ได้ หรือค่าไม่ถูกต้อง ให้ถือเป็น cache miss
- positive cache hit ต้องตรวจ `status == active` และ compare hash แบบ constant-time
- cache ที่ผ่านการ validate แล้วค่อยคืน `user_id` และ `key_id`
- Redis error ระหว่างอ่าน เขียน หรือ parse ใน auth path ให้ตอบ 503 และห้าม fallback ไป database

### Database behavior

เมื่อ positive cache miss:

- query ด้วย `key_id` เท่านั้น
- query ต้องคืนเฉพาะข้อมูลที่จำเป็น: `user_id`, `key_id`, `key_hash`, `status`, `last_used_at`
- กำหนด database timeout 2 วินาที
- ไม่พบ record ให้เขียน negative cache TTL 30 แล้วตอบ 401
- record พบแต่ hash ผิดหรือ status ไม่ active ให้ตอบ 401 แบบเดียวกัน และไม่เขียน negative cache
- database timeout, connection failure หรือ unavailable ให้ตอบ 503 ไม่ใช่ 401
- transaction ownership และการ commit ต้องอยู่นอกขอบเขตเอกสารนี้; auth function ห้ามเพิ่ม side effect ที่ไม่จำเป็นต่อ contract

### Response and observability

credential failure ทุกชนิดต้องเหมือนกันทั้งหมด:

- status 401
- body เดียวกัน
- headers เดียวกัน
- ไม่มี `WWW-Authenticate`
- ไม่มี error code หรือ reason ย่อยที่แยกได้
  สำหรับ server-side audit/log:

- log ได้เฉพาะ `key_id`, `source_ip` และ reason ภายใน
- ห้ามส่ง reason กลับ caller
- failure audit ต้อง aggregate ตาม `(key_id, source_ip)`
- valid auth ต้อง update `last_used_at` ได้ไม่ถี่กว่า 5 นาที
- การ update `last_used_at` ต้องไม่ทำให้ credential ที่ตรวจผ่านแล้วกลายเป็น 401
- ต้องมี policy แยกชัดเจนว่าความล้มเหลวของ update นี้จะตอบ 503 หรือปล่อย success พร้อมบันทึกภายหลัง

## แผน implementation

### Phase 1: กำหนด primitive และ contract

สร้างขอบเขต implementation ใหม่สำหรับ:

- token parser ที่ไม่ทำ I/O
- ULID และ base62 validators
- internal invalid-credential result ที่ map เป็น 401 เดียวกัน
- cache record schema และ key builders
- infrastructure error ที่ map เป็น 503
- result type ที่เปิดเผยเฉพาะ `{user_id, key_id}`

เกณฑ์ผ่าน: token malformed ทุกแบบถูก reject ก่อน dependency ใด ๆ ถูกเรียก และไม่มี raw credential ในค่าที่ส่งออกจาก parser

### Phase 2: ทำ cache และ database port

กำหนด dependency แบบ injectable สำหรับ:

- อ่าน/เขียน negative cache
- อ่าน/เขียน positive cache
- query authentication record
- update `last_used_at`
- บันทึก aggregated auth failure

ทุก port ต้องมี timeout/error contract ที่ทดสอบได้ โดยไม่ผูกกับ implementation อื่นของ workspace

เกณฑ์ผ่าน: Redis failure ไม่เปิดทางไป database และ database failure ไม่ถูกแปลงเป็น 401

### Phase 3: ประกอบ authentication flow

ลำดับภายใน `validate_api_key`:

1. parse และ validate token
2. ตรวจ negative cache
3. hash secret ด้วย SHA-256
4. อ่าน positive cache
5. หาก cache miss ให้ query database
6. ตรวจ field ครบ, status active และ constant-time hash comparison
7. fill positive หรือ negative cache ตามกรณีที่อนุญาต
8. update `last_used_at` ตาม throttle policy
9. บันทึก failure audit เฉพาะฝั่ง server
10. คืน `{user_id, key_id}` จาก authentication record เมื่อผ่าน

ห้ามมี branch ที่ใช้ default identity, ข้อมูลจาก request หรือ fail-open behavior

### Phase 4: เชื่อมเฉพาะ boundary ที่อนุญาต

ตรวจ integration เพียงสองจุด:

- `require_https` ต้องมาก่อนการรับรองตัวตน
- `pre_auth_rate_limit` ต้องผ่านก่อนเรียก `validate_api_key`

ไม่เพิ่มการเรียกหรือการแก้ไข function, service, API หรือ flow อื่นใด

## Test plan

สร้าง test suite เฉพาะของ contract นี้ โดยใช้ fake/in-memory dependencies:

- prefix ผิด, จำนวนส่วนผิด, key id ผิดรูป และ secret ผิดรูป: 401 และยืนยันว่า Redis/DB ไม่ถูกเรียก
- negative cache hit: 401 และไม่ query database
- positive cache hit ที่ field ครบ, active และ hash ตรง: คืน `{user_id, key_id}`
- positive cache ขาด field, parse ไม่ได้ หรือค่าผิดชนิด: cache miss แล้ว query database
- database miss: 401 และเขียน negative cache TTL 30
- hash ผิด, status ไม่ active และ database miss: body/status/header เท่ากัน
- Redis read/write/parse error: 503 และไม่ query database fallback
- database timeout/connection error: 503
- hash comparison ใช้ constant-time path
- positive cache TTL 60 และ negative cache TTL 30
- returned `user_id` ต้องตรงกับ record และไม่มี default identity
- raw token/secret ไม่ปรากฏใน exception, log, audit หรือ return value
- `last_used_at` ไม่ถูก update ถี่เกิน 5 นาที
- boundary order: `require_https` -> `pre_auth_rate_limit` -> `validate_api_key`

## Implementation Checklist

### Contract และ parser

- [ ] กำหนด public contract ของ `validate_api_key(token, source_ip)` แล้ว
- [ ] รองรับรูปแบบ `mthw01_{key_id}_{secret}` เท่านั้น
- [ ] ตรวจ prefix, จำนวนส่วน, ULID 26 ตัว และ base62 secret 32 ตัว
- [ ] malformed token ตอบ 401 โดยไม่เรียก Redis หรือ database
- [ ] raw token และ secret ไม่ออกจาก local scope

### Cache และ database

- [ ] ตรวจ negative cache `auth:neg:{key_id}` ด้วย TTL 30 วินาที
- [ ] ตรวจ positive cache `auth:{key_id}` ด้วย TTL 60 วินาที
- [ ] validate field `user_id`, `key_hash` และ `status` ของ positive cache
- [ ] cache miss query ด้วย `key_id` และ timeout 2 วินาที
- [ ] database miss เขียน negative cache เฉพาะกรณีที่กำหนด
- [ ] Redis error ตอบ 503 และไม่ fallback ไป database
- [ ] database error ตอบ 503 ไม่ถูกกลบเป็น 401

### Authentication และ security

- [ ] hash secret ด้วย SHA-256 และ compare ด้วย constant-time comparison
- [ ] ยอมรับเฉพาะ record ที่มี status `active`
- [ ] คืน `user_id` และ `key_id` จาก authentication record เท่านั้น
- [ ] ไม่มี default identity หรือข้อมูล identity จาก request
- [ ] credential failure ทุกกรณีใช้ 401 contract เดียวกัน
- [ ] ไม่มี `WWW-Authenticate` หรือ reason ย่อยใน response
- [ ] ไม่บันทึก token/secret ใน log, exception, cache หรือ audit
- [ ] กำหนด policy เมื่อ `last_used_at` update ล้มเหลว
- [ ] จำกัด `last_used_at` update ไม่ถี่กว่า 5 นาที

### Boundary และ tests

- [ ] ยืนยันลำดับ `require_https` -> `pre_auth_rate_limit` -> `validate_api_key`
- [ ] ทดสอบทุก malformed token โดยยืนยันว่าไม่มี I/O
- [ ] ทดสอบ cache hit, cache miss และ cache field ไม่ครบ
- [ ] ทดสอบ hash ผิด, status ไม่ active และ database miss ให้ response เหมือนกัน
- [ ] ทดสอบ Redis/DB failure เป็น 503
- [ ] ทดสอบว่า `user_id` ที่คืนตรงกับ authentication record
- [ ] ทดสอบว่าไม่มี raw credential ใน observability data
- [ ] รัน test suite ของ function ผ่าน
- [ ] ตรวจ lint, type check และ format ผ่าน

## คำถามที่ต้องตัดสินใจก่อน implementation

1. authentication record จะใช้ ULID เป็น primary identity หรือเป็น unique key แยกจาก storage id
2. เมื่อ `last_used_at` update ล้มเหลวหลัง auth ผ่าน จะตอบ 503 หรือ success พร้อม deferred audit/update
3. รูปแบบ constant 401 body/header ที่ใช้เป็น public contract
4. กลไก aggregation และการส่ง auth failure audit โดยไม่เพิ่ม background framework ใหม่
5. cache serialization format ที่ validate ได้โดยไม่สร้าง object ที่อาจเก็บ raw credential

## Definition of done

- function นี้ทำงานได้โดยพึ่งพาเฉพาะ input, cache port, database port และ audit port ที่ประกาศในแผน
- `require_https` และ `pre_auth_rate_limit` เป็นเพียง boundary ที่เชื่อมก่อนหน้า
- ไม่มีการอ้างอิงหรือเรียกใช้ส่วนอื่นของโปรเจกต์เดิม
- malformed token ไม่แตะ Redis/DB
- invalid credential ทุกแบบมี 401 contract เดียวกัน
- Redis/DB infrastructure failure fail-closed เป็น 503
- cache TTL, field validation, status check และ constant-time comparison ตรง requirement
- ไม่มี raw token/secret หลุดจาก local scope หรือ observability data
- test suite ครอบคลุม security invariants และ boundary order
