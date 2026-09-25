# Bearer Authentication Plan

สถานะ: เก็บเป็นแนวทางสำหรับการเขียน `llm.router` ใหม่ ยังไม่เปิดใช้งานใน runtime

## หน้าที่ของ `_bearer_token`

`_bearer_token` มีหน้าที่อ่าน header นี้:

```http
Authorization: Bearer <token>
```

และคืนค่าเฉพาะ token ให้ขั้นตอน `validate_api_key(token, source_ip)` ตรวจสอบต่อ

ฟังก์ชันนี้ไม่ควรทำหน้าที่ตรวจ secret, query database, อ่าน Redis หรือสร้าง identity เอง เพราะงานเหล่านั้นเป็นความรับผิดชอบของ auth service

## แนวทางการ wire

เมื่อ `llm.router` ถูกเขียนใหม่ ให้ wire authentication เป็น FastAPI dependency ของ endpoint ที่ต้องการ auth:

```text
require_https
    -> pre_auth_rate_limit
  -> extract bearer token
  -> validate_api_key
  -> llm service
```

ตัวอย่างโครงสร้าง:

```python
async def require_api_key(...) -> ApiKeyIdentity:
    token = _bearer_token(request)
    return await validate_api_key(token, source_ip, ...)


@router.post("/llm/chat")
async def chat(
    identity: ApiKeyIdentity = Depends(require_api_key),
):
    ...
```

รายละเอียด dependency จริงต้องสอดคล้องกับการจัดการ session, Redis และ trusted proxy ของ router เวอร์ชันใหม่

## เหตุผลที่ไม่ใช้ middleware

ไม่ใช้ middleware สำหรับ `_bearer_token` เพราะ bearer authentication เป็นข้อกำหนดของ endpoint บางกลุ่ม ไม่ใช่ทุก request ในระบบ

การใช้ dependency ทำให้:

- ระบุได้ชัดว่า route ใดต้องใช้ API key
- inject identity ที่ตรวจแล้วเข้า route ได้โดยตรง
- ทดสอบ route และ auth flow แยกกันได้
- ไม่บังคับ health check หรือ endpoint สาธารณะให้ต้องมี bearer token
- รักษา layering เดิม: router รับผิดชอบ HTTP และ service รับผิดชอบ business/auth logic

middleware เหมาะกับ cross-cutting concern ระดับทั้งแอป เช่น HTTPS, CORS หรือ request logging มากกว่า

## Error contract

ทุก error จาก auth flow ต้องผ่าน `AppError` และ error envelope เดียวกัน:

- ไม่มี `Authorization` header หรือ scheme ไม่ใช่ `Bearer` -> credential error ที่เป็น 401
- token ผิดรูปหรือ API key ใช้ไม่ได้ -> ให้ `validate_api_key` จัดการตาม contract เดิม
- Redis หรือ database ใช้งานไม่ได้ -> ให้ auth service คืน error ระดับ infrastructure ตาม contract เดิม
- ห้ามคืน raw token หรือ secret ใน error, log, audit หรือ response

credential failure ที่เป็น 401 ควรมี response contract เดียวกัน เพื่อไม่เปิดเผยว่าความผิดพลาดเกิดจาก token ส่วนใด

## สถานะปัจจุบัน

ตอนนี้ `_bearer_token` ไม่มีอยู่ใน `api/app` และไม่มี caller ที่ทำงานอยู่ `llm.router` ยังถูกปิดไว้เพราะกำลังเขียนใหม่ ดังนั้นยังไม่ต้องสร้าง helper หรือ wire dependency เพิ่มในตอนนี้

เมื่อเริ่ม implementation ของ router ใหม่ ให้สร้างและทดสอบ `_bearer_token` ใน auth dependency เดียวกับการ wire `validate_api_key` แล้วค่อยเปิด `llm.router` หลังจากตรวจ error envelope และ integration flow ครบ
