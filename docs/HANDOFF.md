# Handoff — API key และ chat pipeline

เอกสารนี้สรุปสิ่งที่ทีมเราส่งมอบ สิ่งที่ยังไม่ได้ทำ และเรื่องที่ **เจ้าของแอปต้องตัดสินใจเอง**
เพราะทีมเราไม่มีข้อมูลพอจะตัดสินแทน อ่านหัวข้อ 1 ก่อน เพราะเป็นเรื่องที่ขวางการขึ้น production

สถานะ ณ commit `8da18c0` บน branch `develop` (2026-09-25)

---

## 0. สรุปสั้น

**ทำเสร็จและทดสอบแล้ว**

- จัดการ API key: สร้าง ดูรายการ เพิกถอน และลบ (`/v1/api-keys/*`)
- ตรวจ API key แบบ fail closed (Redis หรือ DB ล่มได้ 503 ไม่ใช่ 401)
- `POST /v1/chat/completions` ตอบกลับรูปแบบเดียวกับ OpenAI ทดสอบกับ OpenAI Python SDK แล้ว
- quota แบบจองก่อนเรียก แล้วหักตามจริงหลังเรียก เก็บใน Redis ของแอปหลัก
- rate limit สามชั้น: ต่อ IP ก่อนตรวจ key, ต่อ key (จำนวนคำขอและจำนวน token), และต่อ user สำหรับหน้าจัดการ key
- เปิดหรือปิด model โดย admin (`/v1/admin/models/*`)
- หน้า Usage ใน dashboard และเอกสารสาธารณะที่ `/docs` (ไทยและอังกฤษ)
- job ลบ log ที่เกินอายุ และ job ตรวจรูปแบบ quota ของแอปหลัก
- test ฝั่ง API 194 ตัว (รันกับ MySQL และ Redis จริง) และฝั่ง web 79 ตัว

**ขึ้น production ยังไม่ได้** จนกว่าจะปิดเรื่องในหัวข้อ 1 ครบ โดยเฉพาะข้อ 1.1 เพราะตอนนี้
หน้า API Keys และ Usage ตอบ 401 ทุกคำขอใน production

**เอกสารที่เกี่ยวข้อง**

| เอกสาร                           | มีอะไร                                                               |
| -------------------------------- | -------------------------------------------------------------------- |
| `docs/planning/chat_pipeline.md` | spec ของ chat pipeline และหมายเหตุว่า implement ต่างจาก spec ตรงไหน  |
| `docs/DECISIONS.md`              | เหตุผลของการตัดสินใจทั้งหมด                                          |
| `docs/NON_FUNCTIONAL.md`         | กฎด้าน maintainability / scalability / availability และสถานะปัจจุบัน |
| `docs/DB_PERMISSIONS.md`         | สิทธิ์ของ DB user แต่ละตัว พร้อม SQL                                 |
| `CLAUDE_CODE_BRIEF.md`           | brief เดิมของงาน API key และกฎ 10 ข้อจาก threat model                |

---

## 1. เรื่องที่ต้องตอบก่อนขึ้น production

### 1.1 Session ของแอปหลัก — ขวางทุกอย่างในหน้า dashboard

หน้า API Keys, Usage และ admin ถูกเรียกจากเบราว์เซอร์ด้วย session ของแอปหลัก ไม่ใช่ API key
ทีมเราไม่รู้ว่า session ทำงานอย่างไร จึงทำให้ **ทุกคำขอตอบ 401** ไว้ก่อน (fail closed)
ยกเว้นในเครื่อง dev ที่ตั้ง `ENV=dev` และ `DEV_SESSION_USER_ID`

**ต้องการคำตอบ**

1. session เป็น cookie, JWT หรือเก็บฝั่ง server — ชื่อ cookie หรือ header คืออะไร
2. service นี้ตรวจ session ได้เองหรือไม่ (เช่นมี public key ของ JWT) หรือต้องถามแอปหลักทุกครั้ง
3. `user_id` เป็นจำนวนเต็มหรือไม่ (ฝั่งเราเก็บเป็น `INT`)
4. role admin มาจากไหน — อยู่ใน session หรือต้องไปอ่านจากที่อื่น
5. แอปหลักกับ dashboard อยู่คนละ origin หรือไม่ (มีผลกับ CORS และ cookie)

**งานที่ต้องทำหลังได้คำตอบ**

| ที่                                                             | งาน                                                                              |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `api/app/services/session_auth.py` → `_verify_main_app_session` | ตรวจ session แล้วคืน `Principal(user_id, role)` หรือ `None` (มี `TODO(session)`) |
| `api/app/main.py`                                               | ถ้าใช้ cookie ต้องเปิด `allow_credentials=True` และจำกัด `CORS_ORIGINS` ให้แคบ   |
| `web/src/utils/AxiosUtil.ts`                                    | ส่ง session ไปกับคำขอ เช่น `withCredentials: true` (มี `TODO(session)`)          |
| `web/src/components/layout/dashboard.tsx`                       | แสดงชื่อผู้ใช้ที่ login อยู่แทนข้อความ "Your account"                            |

**ข้อควรรู้:** ตาราง `identity_users` ฝั่งเราเก็บแค่ `id` ของผู้ใช้จากแอปหลัก
สร้างอัตโนมัติตอนผู้ใช้สร้าง key ครั้งแรก ไม่ต้อง sync ข้อมูลอื่น

### 1.2 Quota ใน Redis ของแอปหลัก — ต้องยืนยันสัญญาร่วมกัน

chat pipeline อ่านและเขียน Redis hash `quota:{user_id}` ของแอปหลักโดยตรง
ถ้าสองระบบเข้าใจไม่ตรงกัน ยอด quota จะผิดโดยไม่มีใครรู้

**ต้องการคำตอบหรือการยืนยัน**

1. **แอปหลักต้องเพิ่ม `used` ด้วย `HINCRBY` เท่านั้น** ถ้าใช้วิธีอ่านค่าแล้ว `HSET` ค่าใหม่กลับไป
   จะเขียนทับยอดที่ฝั่งเราหักไปแล้ว — เรื่องนี้สำคัญที่สุดในหัวข้อนี้
2. field `limit` และ `used` เป็นจำนวนเต็มไม่ติดลบ เก็บเป็นตัวเลขล้วน (เช่น `"1000"` ไม่ใช่ `"1,000"`)
3. ใครสร้าง `quota:{user_id}` และสร้างเมื่อไร — ตอนนี้ถ้าไม่มี key ฝั่งเราถือว่า `used = 0`
   และใช้ `limit` จาก `LLM_TOKEN_QUOTA` (ค่าเริ่มต้น 1,000,000)
4. **Redis ต้องเป็น instance เดียวกันกับที่ service นี้ใช้ และไม่ใช่ Redis Cluster**
   script ตอนจอง quota แตะสอง key พร้อมกัน (`api:quota:resv:{user_id}` ของเรา และ `quota:{user_id}` ของแอปหลัก)
   ใน Cluster สอง key นี้อาจอยู่คนละ slot แล้ว Redis จะปฏิเสธ (`CROSSSLOT`)
   ถ้าต้องใช้ Cluster ต้องตกลงชื่อ key ใหม่ที่ใช้ hash tag ร่วมกัน เช่น `quota:{42}` กับ `api:quota:resv:{42}`
5. quota รีเซ็ตรอบไหน (รายวัน รายเดือน) และใครรีเซ็ต — ฝั่งเราไม่รีเซ็ตเอง

**พฤติกรรมที่ตั้งไว้แล้ว**

- ค่าใน `quota:{user_id}` ผิดรูปแบบ → ตอบ 503 และเขียน log `ALERT` ไม่เดา
- quota หมด → ตอบ 422 `llm_quota_exceeded` โดยไม่บอกยอดคงเหลือ
- ยอดคงเหลือแสดงเฉพาะในหน้า Usage ไม่ส่งผ่าน public API
- ฝั่งเราไม่เพิ่ม field ใหม่ใน `quota:{user_id}` ยอดที่จองไว้อยู่ใน sorted set แยก

### 1.3 nginx หน้า API

ฝั่งเราเชื่อ header จาก proxy เฉพาะเมื่อคำขอมาจาก IP ใน `TRUSTED_PROXY_IPS`
ถ้า nginx ไม่ตั้ง header ครบ **ทุกคำขอไปที่ public API (`/v1/chat/completions`) จะได้ 400**
(หน้า dashboard ไม่บังคับ header เหล่านี้ ใช้แค่บันทึก IP ลง audit log)

ต้องยืนยันว่า nginx ตั้งค่าดังนี้ (ต้องใช้ `proxy_set_header` ซึ่งเขียนทับค่าจาก client ไม่ใช่ต่อท้าย)

```nginx
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Request-Id      $request_id;   # ไม่บังคับ แต่ทำให้ log ของ nginx กับเราโยงกันได้
```

และบอก IP ของ nginx มาใส่ `TRUSTED_PROXY_IPS` รวมถึงบอกว่ามี proxy กี่ชั้น
(ตอนนี้รองรับ proxy ชั้นเดียวหน้า API)

### 1.4 ผู้ให้บริการโมเดล

- **ยืนยันว่าใช้ OpenAI** — เอกสาร `/docs` ตอนนี้ระบุ OpenAI และลิงก์นโยบาย `https://openai.com/enterprise-privacy/`
  ถ้าจะเปลี่ยน ต้องแก้ทั้ง `LLM_BASE_URL` และ `web/src/content/docs/values.ts`
- **API key ของ provider แยกตาม environment** (dev / staging / production) ใส่เป็นไฟล์จาก secret store
  แล้วชี้ด้วย `LLM_API_KEY_FILE` ระบบอ่านไฟล์ทุกครั้งที่เรียก จึงเปลี่ยน key ได้โดยไม่ต้อง restart
  staging และ production **จะไม่ยอม start** ถ้าไม่มีไฟล์นี้
- **ยังไม่เคยทดสอบกับ OpenAI จริง** ที่ทดสอบผ่านคือ provider ปลอมที่ตอบรูปแบบเดียวกัน
  ต้องลองยิงจริงอย่างน้อยหนึ่งครั้งหลังใส่ key

---

## 2. ค่าที่เป็นตัวเลขชั่วคราว — เจ้าของแอปต้องตัดสินใจ

ค่าทั้งหมดนี้ทีมเราตั้งไว้เพื่อให้ระบบทำงานได้ **ไม่ได้มาจากข้อมูลการใช้งานจริงหรือต้นทุนจริง**
แต่ละค่ามีเหตุผลเขียนไว้ในไฟล์ที่ระบุ แก้ได้ที่ไฟล์นั้นที่เดียว

### 2.1 ค่าที่กระทบผู้ใช้และค่าใช้จ่ายโดยตรง

| ค่า                                          | ตอนนี้                                              | ไฟล์                                              | ต้องคิดเรื่อง                                                                        |
| -------------------------------------------- | --------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------ |
| quota เริ่มต้นเมื่อแอปหลักไม่ได้ตั้ง `limit` | 1,000,000 token                                     | env `LLM_TOKEN_QUOTA`                             | ควรเป็นเท่าไร หรือควรปฏิเสธถ้าไม่มี `limit` เลย                                      |
| จำนวน key ที่ active ได้ต่อบัญชี             | 5                                                   | `api/app/constants/api_keys.py` `MAX_ACTIVE_KEYS` |                                                                                      |
| rate limit จำนวนคำขอ (เรียกผ่าน API key)     | เก็บได้ 10 คำขอ เติม 20 ต่อนาที                     | `api/app/constants/perkey_rate_limit.py`          | นับต่อบัญชี ทุก key ของบัญชีใช้ถังเดียวกัน                                           |
| rate limit จำนวน token (เรียกผ่าน API key)   | เก็บได้ 20,000 เติม 20,000 ต่อนาที                  | ไฟล์เดียวกัน                                      | ต้องไม่น้อยกว่า input สูงสุด + output สูงสุด (ตอนนี้ 12,288) ไม่งั้นระบบไม่ยอม start |
| input สูงสุดต่อคำขอ                          | 8,192 token                                         | ไฟล์เดียวกัน `MAX_INPUT_TOKENS`                   |                                                                                      |
| output สูงสุดต่อคำขอ                         | 4,096 token                                         | `api/app/constants/llm.py` `POLICY_CAP`           | ค่าจริงคือค่าที่น้อยที่สุดระหว่างนี้ ค่าของ model และค่าที่ผู้ใช้ขอ                  |
| output สูงสุดของแต่ละ model                  | gpt-4o 16,384 / gpt-4.1 32,768                      | ตาราง `llm_models` คอลัมน์ `max_output_tokens`    | ค่าจาก migration ตามที่ OpenAI ประกาศ ควรตรวจอีกครั้ง                                |
| รายชื่อ model ที่เปิดให้ใช้                  | `gpt-4o`, `gpt-4.1`                                 | ตาราง `llm_models`                                | เพิ่มได้ด้วย SQL ส่วนการเปิดหรือปิดทำผ่าน `/v1/admin/models/*`                       |
| rate limit ต่อ IP ก่อนตรวจ key               | เก็บได้ 60 เติม 1 ต่อวินาที                         | `api/app/services/pre_auth_rate_limit.py`         | นับเฉพาะคำขอที่ key ผิด IP ที่คนใช้ร่วมกันมาก (เช่นออฟฟิศ) อาจชนเร็ว                 |
| rate limit หน้าจัดการ key                    | อ่าน 60 เติม 1 ต่อวินาที / เขียน 10 เติม 10 ต่อนาที | `api/app/constants/mgmt_rate_limit.py`            |                                                                                      |

### 2.2 อายุการเก็บข้อมูล (มีผลทางกฎหมายและนโยบายความเป็นส่วนตัว)

| ข้อมูล                                                      | เก็บกี่วัน   | ไฟล์                             |
| ----------------------------------------------------------- | ------------ | -------------------------------- |
| usage log (`llm_usage_logs`)                                | 60           | `api/app/constants/retention.py` |
| log การเรียก provider (`llm_provider_call_logs`)            | 60           | ไฟล์เดียวกัน                     |
| audit log ของ key (`identity_api_key_audit_logs`)           | 90           | ไฟล์เดียวกัน                     |
| log การยืนยันตัวตนที่ไม่ผ่าน (`identity_auth_failure_logs`) | 90           | ไฟล์เดียวกัน                     |
| key ที่ถูกลบแบบ soft delete                                 | 90 วันหลังลบ | ไฟล์เดียวกัน                     |

ถ้าเปลี่ยนตัวเลขเหล่านี้ ต้องแก้เอกสาร `/docs` (`web/src/content/docs/values.ts` ส่วน `retentionDays`) ให้ตรงด้วย
และหน้า Usage ย้อนหลังได้ไม่เกินอายุของ usage log

log ทุกตัวเก็บเฉพาะ metadata **ไม่เก็บเนื้อหา prompt หรือคำตอบ** ถ้าจะเปลี่ยนเรื่องนี้ต้องแก้เอกสารด้านความเป็นส่วนตัวด้วย

### 2.3 ค่าด้านระบบ (ปรับเมื่อมีตัวเลขจาก traffic จริง)

| ค่า                                              | ตอนนี้                             | ไฟล์                                  | หมายเหตุ                                                                               |
| ------------------------------------------------ | ---------------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------- |
| จำนวนการเรียก provider พร้อมกันต่อ process       | 50                                 | `api/app/constants/llm.py`            | เกินแล้วตอบ 503 ทันที ไม่รอคิว                                                         |
| timeout ไป provider                              | connect 5 วินาที / read 120 วินาที | ไฟล์เดียวกัน                          |                                                                                        |
| เวลาที่จอง quota ค้างไว้                         | 300 วินาที                         | ไฟล์เดียวกัน                          | ต้องไม่น้อยกว่า 2 เท่าของ read timeout ไม่งั้นระบบไม่ยอม start                         |
| อายุ cache รายชื่อ model                         | 300 วินาที                         | ไฟล์เดียวกัน                          |                                                                                        |
| อายุ `Idempotency-Key`                           | 300 วินาที                         | ไฟล์เดียวกัน                          |                                                                                        |
| ขนาดคำขอสูงสุด / คำตอบจาก provider สูงสุด        | 1 MB / 10 MB                       | ไฟล์เดียวกัน                          |                                                                                        |
| ค่าคลาดเคลื่อนที่ยอมรับได้ของ usage จาก provider | ±50% ของค่าที่เราประมาณ            | ไฟล์เดียวกัน                          | เกินนี้จะหัก quota ตามค่าประมาณแทน                                                     |
| วิธีประมาณ token                                 | จำนวน byte ของ UTF-8 หาร 4         | `api/app/services/tokens.py`          | ภาษาไทยจะประมาณเกินเล็กน้อย ควรเทียบกับตัวเลขจริงใน metric `llm_prompt_estimate_ratio` |
| อายุ cache ของ key ที่ผ่านการตรวจ                | 60 วินาที                          | `api/app/constants/auth.py`           | เป็นช่วงเวลาที่ key ที่เพิ่ง revoke อาจยังใช้ได้ในกรณีล้าง cache ไม่สำเร็จ             |
| timeout ของ Redis / MySQL                        | 1 วินาที / 2 วินาที                | `api/app/constants/infra.py`          |                                                                                        |
| ขนาด connection pool ของ MySQL                   | 20 + overflow 10                   | env `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | DB ใช้ร่วมกับแอปหลัก ต้องดูว่ารับได้หรือไม่                                            |

### 2.4 ค่าในเอกสาร `/docs` ที่ยังเป็น TBD

ไฟล์ `web/src/content/docs/values.ts` ยังมีค่าชั่วคราวที่ตั้งใจให้ดูออกว่าเป็นค่าปลอม

| ค่า                  | ตอนนี้                           | ต้องใส่                                                   |
| -------------------- | -------------------------------- | --------------------------------------------------------- |
| `baseUrl`            | `https://api.example.invalid/v1` | URL จริงของ production                                    |
| model ฝั่ง embedding | `embed-a`, context 0             | ชื่อ model จริง หรือลบออกถ้าไม่ทำ embeddings (ดูหัวข้อ 3) |

ค่าเหล่านี้จะแสดงป้าย "To be confirmed" ในหน้าเว็บ
และ `bun run --cwd web build` (build สำหรับ release) **จะไม่ผ่าน** จนกว่าจะแก้ครบ ซึ่งตั้งใจให้เป็นอย่างนั้น

ค่าอื่นในไฟล์นี้ เช่น rate limit และรายชื่อ model คัดลอกมาจากค่าใน API ถ้าเปลี่ยนค่าใน API ต้องแก้ไฟล์นี้ตามด้วยมือ
(ในอนาคตควรให้ API มี endpoint ส่งค่าเหล่านี้มาเอง — `TODO(limits-endpoint)`)

---

## 3. สิ่งที่ยังไม่ได้ทำ

| เรื่อง                                                    | สถานะ               | หมายเหตุ                                                                                                                                                                  |
| --------------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ตรวจ session ของแอปหลัก                                   | ยังไม่ทำ            | รอคำตอบข้อ 1.1                                                                                                                                                            |
| `POST /v1/embeddings`                                     | ยังไม่ทำ            | ไม่อยู่ใน spec แต่เอกสาร `/docs` มีหน้า reference ไว้แล้ว ต้องเลือกว่าจะทำหรือจะเอาหน้านั้นออก                                                                            |
| `GET /v1/models`                                          | ยังไม่ทำ            | เหตุผลเดียวกัน OpenAI SDK บางตัวเรียก endpoint นี้                                                                                                                        |
| streaming (`stream: true`)                                | ตั้งใจไม่ทำ         | ปฏิเสธด้วย 400 อย่างชัดเจน ถ้าจะทำต้องออกแบบการหัก quota และ timeout ใหม่                                                                                                 |
| tools / function calling                                  | ตั้งใจไม่ทำ         | ปฏิเสธด้วย 400                                                                                                                                                            |
| หน้า admin สำหรับจัดการ model                             | ทำแล้ว              | อยู่ที่ `/admin/models` **ยังไม่มีลิงก์ใน sidebar** เพราะ web ยังไม่รู้ role ของผู้ใช้จนกว่าจะต่อ session (ข้อ 1.1) คนที่ไม่ใช่ admin เปิดแล้วจะเห็นข้อความว่าเฉพาะ admin |
| checkbox ยอมรับเรื่องส่งข้อมูลให้บุคคลที่สาม ตอนสร้าง key | ทำแล้ว              | บังคับแค่ฝั่งหน้าเว็บ backend ไม่ตรวจ (ตาม spec) ชื่อผู้ให้บริการดึงจาก `web/src/content/docs/values.ts`                                                                  |
| circuit breaker ไป provider                               | เลื่อนไว้           | timeout และการจำกัดจำนวนการเรียกพร้อมกันกันเส้นทางหลักได้แล้ว ทบทวนเมื่อมี metric จริง                                                                                    |
| กันการยิง `Idempotency-Key` เดียวกันพร้อมกัน              | ยังไม่ทำ            | ถ้าส่งสองคำขอพร้อมกันด้วย key เดียวกัน อาจเรียก provider ทั้งสองครั้ง                                                                                                     |
| endpoint ส่งค่า limit ให้หน้า `/docs`                     | ยังไม่ทำ            | `TODO(limits-endpoint)`                                                                                                                                                   |
| CI                                                        | ยังไม่มี            | ดูหัวข้อ 4.6                                                                                                                                                              |
| `bun run gen:api`                                         | พังเพราะ dependency | ดูหัวข้อ 4.7                                                                                                                                                              |

---

## 4. งานฝั่ง ops ก่อนขึ้นระบบ

### 4.1 Environment variables

ตัวอย่างไฟล์: `api/.env.example` สำหรับเครื่อง dev และ `api/.env.production.example` สำหรับ staging และ production (ช่องที่ต้องกรอกเขียนเป็น `<...>`) ส่วนฝั่ง web ใช้ `web/.env.example`

ตัวแปรที่เป็นรายการ (`TRUSTED_PROXY_IPS`, `ALLOWED_HOSTS`, `CORS_ORIGINS`) ใส่เป็น JSON เช่น `["10.0.0.5"]`

| ตัวแปร                                    | จำเป็น                    | หมายเหตุ                                                                    |
| ----------------------------------------- | ------------------------- | --------------------------------------------------------------------------- |
| `ENV`                                     | ใช่                       | `production`, `staging`, `test` หรือ `dev` ถ้าไม่ตั้งจะถือเป็น `production` |
| `DATABASE_URL`                            | ใช่                       | ใช้ DB user ของแอป ไม่ใช่ user ที่รัน migration                             |
| `REDIS_URL`                               | ใช่                       | Redis เดียวกับที่มี `quota:{user_id}` ของแอปหลัก (ข้อ 1.2)                  |
| `LLM_API_KEY_FILE`                        | ใช่ (staging, production) | path ของไฟล์ key จาก secret store                                           |
| `LLM_BASE_URL`                            | ไม่                       | ค่าเริ่มต้น `https://api.openai.com/v1`                                     |
| `LLM_TOKEN_QUOTA`                         | ไม่                       | ข้อ 2.1                                                                     |
| `TRUSTED_PROXY_IPS`                       | ใช่                       | IP ของ nginx (ข้อ 1.3)                                                      |
| `ALLOWED_HOSTS`                           | ใช่                       | hostname จริงของ API                                                        |
| `CORS_ORIGINS`                            | ใช่                       | origin ของ dashboard                                                        |
| `APP_TZ`                                  | ไม่                       | ค่าเริ่มต้น `Asia/Bangkok`                                                  |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`         | ไม่                       | ข้อ 2.3                                                                     |
| `QUOTA_HEALTH_USER_ID`                    | ใช่ ถ้ารัน job ตรวจ quota | บัญชีทดสอบที่มี `quota:{user_id}` จริง                                      |
| `DEV_SESSION_USER_ID`, `DEV_SESSION_ROLE` | **ห้ามตั้ง** นอก dev      | ถ้าตั้งใน environment อื่น API จะไม่ยอม start                               |
| `LLM_API_KEY`                             | ห้ามใช้ นอก dev           | ใช้ใน dev เท่านั้น                                                          |

### 4.2 Database

- สร้าง DB user แยกสามตัว: user ของแอป, user ที่รัน job ลบ log และ user ที่รัน migration
  SQL สำหรับ grant อยู่ใน `docs/DB_PERMISSIONS.md` ตาราง audit และ log ให้สิทธิ์แค่ `INSERT` เพื่อไม่ให้แก้ย้อนหลังได้
- migration มีสามตัว รันด้วย `uv run --directory api alembic upgrade head`
- **migration ตัวแรก (`20260925_schema`) มาแทน migration เดิม `20260905_llm`**
  DB ที่เคยสร้างจาก migration เดิมต้องสร้างใหม่ อัปเกรดทับไม่ได้
- migration `20260925_chat` **ลบตาราง `llm_quotas`** ถ้ามีข้อมูลในตารางนั้นที่ต้องเก็บ ให้ย้ายออกก่อน
- ตาราง `identity_*` และ `llm_*` ใช้ DB ร่วมกับแอปหลัก ชื่อตารางมี prefix แยกไว้แล้ว

### 4.3 Job ที่ต้องตั้ง cron

```bash
# ทุกวัน: ลบ log และ key ที่เกินอายุ — ใช้ DB user ของ job ลบ log
uv run --directory api python -m app.jobs.retention

# ทุกไม่กี่นาที: ตรวจว่า quota:{user_id} ของแอปหลักยังมีรูปแบบเดิม
uv run --directory api python -m app.jobs.quota_health
```

`quota_health` ออกด้วย exit code 1 เมื่อพบปัญหา ใช้เป็นสัญญาณแจ้งเตือนได้

### 4.4 การแจ้งเตือน

ระบบเขียน log ขึ้นต้นด้วย `ALERT` เมื่อเกิดเรื่องที่คนต้องรู้ทันที ต้องส่ง log เหล่านี้เข้าระบบแจ้งเตือน เช่น

- ล้าง cache ไม่สำเร็จตอน revoke key หรือปิด model (key หรือ model อาจยังใช้ได้อีกไม่เกิน 60 หรือ 300 วินาที)
- ค่าใน `quota:{user_id}` ผิดรูปแบบ (แอปหลักอาจเปลี่ยน schema)
- อ่านไฟล์ key ของ provider ไม่ได้ หรือไม่มี key
- เขียน usage log หรือ provider call log ไม่สำเร็จ

### 4.5 Metrics

`GET /metrics` เป็นรูปแบบ Prometheus เปิดให้เฉพาะ localhost และ IP ใน `TRUSTED_PROXY_IPS`
ตัวที่ควรตั้ง dashboard และ alert:

| metric                                                  | ดูอะไร                                                                      |
| ------------------------------------------------------- | --------------------------------------------------------------------------- |
| `llm_provider_calls_total{outcome}`                     | สัดส่วนผลการเรียก provider เช่น `timeout`, `provider_error`, `rate_limited` |
| `llm_usage_validation_failures_total`                   | provider ส่ง usage ที่เชื่อไม่ได้บ่อยแค่ไหน                                 |
| `llm_prompt_estimate_ratio`                             | ค่าประมาณ token ของเราแม่นแค่ไหน                                            |
| `llm_outbound_in_flight`, `llm_outbound_rejected_total` | ใกล้ชนเพดานการเรียกพร้อมกันหรือยัง                                          |
| `llm_idempotent_replays_total`                          | ลูกค้า retry ด้วย `Idempotency-Key` บ่อยแค่ไหน                              |

### 4.6 CI

ยังไม่มี CI เมื่อตั้ง ให้รัน `bun run gates` โดยมี MySQL และ Redis จาก `docker-compose.yml`
และ **ตั้ง `REQUIRE_INFRA=1`** ไม่งั้น test ที่ต้องใช้ DB จริงจะถูกข้าม แทนที่จะ fail

### 4.7 Build ฝั่ง web

- `bun run gates` ใช้ `build:check` ซึ่งไม่ตรวจค่า TBD ในเอกสาร
- pipeline สำหรับ release ต้องใช้ `bun run --cwd web build` ซึ่งจะ fail ถ้ายังมีค่า TBD (ข้อ 2.4)
- `bun run gen:api` พังเพราะ bun วาง `ajv` คนละเวอร์ชันไว้ใน `node_modules` วิธีแก้ชั่วคราวอยู่ใน `docs/DECISIONS.md`
  หัวข้อ "Tried and did not work" ต้องหาทางแก้ถาวร

---

## 5. ข้อจำกัดที่รู้และยอมรับไว้

- **revoke key อาจมีผลช้าได้ถึง 60 วินาที** ถ้าล้าง cache ไม่สำเร็จ ระบบจะตอบ 500 ให้ผู้ใช้กดใหม่ ไม่บอกว่าสำเร็จ
- **ปิด model อาจมีผลช้าได้ถึง 300 วินาที** ด้วยเหตุผลเดียวกัน แต่ก่อนเรียก provider ระบบอ่านสถานะ model จาก DB ซ้ำอีกครั้งเสมอ
- **ถ้า Redis ล่ม API ทั้งหมดตอบ 503** เป็นการออกแบบให้ fail closed ไม่อ่าน DB แทนทุกคำขอ เพื่อไม่ให้ภาระไปตกที่ DB ที่ใช้ร่วมกับแอปหลัก
- **ถ้าการจอง quota หมดอายุก่อนหักจริง จะไม่หัก quota** (ตาม spec) ในทางปฏิบัติไม่ควรเกิด เพราะเวลาจองยาวกว่า timeout มาก
- **กดสร้าง key สองครั้งพร้อมกันได้ key สองตัว** ยอมรับตาม spec มีป้าย "Never used" และปุ่ม discard ช่วย
- **ข้อความ error ของ chat ใช้รูปแบบ envelope ของเรา** ไม่ใช่รูปแบบ error ของ OpenAI ตรงตัว OpenAI SDK อ่าน `error.message` ได้ปกติ
- **จำกัดการเรียกพร้อมกันนับต่อ process** ถ้ารันหลาย process หรือหลายเครื่อง เพดานรวมคือ 50 × จำนวน process

---

## 6. Redis key ที่ service นี้ใช้

แอปหลักควรรู้ไว้เพื่อไม่ให้ชื่อชนกัน

| key                                            | เจ้าของ     | ใช้ทำอะไร                                                              |
| ---------------------------------------------- | ----------- | ---------------------------------------------------------------------- |
| `quota:{user_id}`                              | **แอปหลัก** | `limit` และ `used` ฝั่งเราอ่าน และเพิ่ม `used` ด้วย `HINCRBY` เท่านั้น |
| `api:quota:resv:{user_id}`                     | เรา         | quota ที่จองไว้ระหว่างรอ provider                                      |
| `auth:{key_id}`, `auth:neg:{key_id}`           | เรา         | cache ผลตรวจ API key                                                   |
| `model:enabled`                                | เรา         | cache รายชื่อ model ที่เปิดอยู่                                        |
| `idem:{key_id}:{idempotency_key}`              | เรา         | คำตอบที่เก็บไว้สำหรับ `Idempotency-Key`                                |
| `rl:ip:*`, `rl:req:*`, `rl:tok:*`, `rl:mgmt:*` | เรา         | rate limit                                                             |

---

## 7. รันในเครื่อง

```bash
bun install
uv sync --directory api --all-groups
cp api/.env.example api/.env          # มี ENV=dev และ DEV_SESSION_USER_ID=1 อยู่แล้ว
cp web/.env.example web/.env
docker compose up -d                  # MySQL :3310, Redis :6389
uv run --directory api alembic upgrade head
bun run api                           # http://localhost:8000
bun run web                           # http://localhost:5173
bun run gates                         # ตรวจทุกอย่างก่อน commit
```

ถ้าจะลองเรียก chat ในเครื่อง ต้องใส่ `LLM_API_KEY` ใน `api/.env` และตั้งค่า quota ใน Redis ก่อน เช่น
`redis-cli -p 6389 HSET quota:1 limit 1000000 used 0`
แล้วส่ง header `X-Forwarded-Proto: https` และ `X-Real-IP` แทน nginx

---

## 8. เช็กลิสต์สำหรับเจ้าของแอป

- [ ] ตอบเรื่อง session ของแอปหลัก (ข้อ 1.1)
- [ ] ยืนยันว่าแอปหลักเพิ่ม `used` ด้วย `HINCRBY` และตกลงรูปแบบ `quota:{user_id}` (ข้อ 1.2)
- [ ] ยืนยันว่า Redis เป็น instance เดียวกัน และไม่ใช่ Cluster (ข้อ 1.2)
- [ ] ยืนยันการตั้งค่า nginx และ IP ของ proxy (ข้อ 1.3)
- [ ] ยืนยันผู้ให้บริการโมเดล และเตรียม key แยกตาม environment (ข้อ 1.4)
- [ ] ตัดสินค่าในหัวข้อ 2.1 และ 2.2 โดยเฉพาะ quota, rate limit และอายุการเก็บข้อมูล
- [ ] ใส่ `baseUrl` จริง และตัดสินเรื่อง embeddings (ข้อ 2.4 และหัวข้อ 3)
- [ ] ตัดสินว่าจะทำ `/v1/embeddings` และ `/v1/models` หรือไม่ และจะใส่ลิงก์หน้า `/admin/models` ใน sidebar อย่างไร (หัวข้อ 3)
- [ ] ตั้ง DB user, cron, การแจ้งเตือน, metrics และ CI (หัวข้อ 4)
- [ ] ลองเรียก `/v1/chat/completions` กับ OpenAI จริงหนึ่งครั้งก่อนเปิดให้ผู้ใช้
