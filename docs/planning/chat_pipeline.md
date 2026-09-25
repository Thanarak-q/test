# Chat pipeline — spec

The spec the chat pipeline, quota, model catalogue and key management are built from
(2026-09-25). Kept as written; where the implementation had to interpret it, the
**Implementation notes** at the end say how and why.

## POST /v1/chat/completions

```
func chat(request, body) -> response

 0. peer = require_https(request)              -> 400
 1. client_ip = get_client_ip(request, peer)   -> 400
 2. rate_limit = preauth_rate_limit(client_ip) -> 429
 3. identity = validate_api_key(token, ip)     -> 401
    -> {user_id, key_id}
    refund_pre_auth_token(client_ip)
 4. reject unsupported params                  -> 400
    - stream=true, tools, functions, n>1
    - ปฏิเสธชัด ๆ ไม่ใช่ ignore
      stream ที่ถูก ignore จะทำให้ SDK รอ chunk ที่ไม่มีวันมา
 5. model_validate(body.model)                 -> 403      ← ย้ายขึ้น
    -> {model_id, context_window, max_output}
    - ถูกกว่า rate limit (cache hit เกือบตลอด)
      และปฏิเสธได้โดยไม่กิน bucket ของผู้ใช้
 6. cap = min(body.max_tokens, model.max_output, POLICY_CAP)  ← ย้ายขึ้น
 7. est = estimate_tokens(body.messages) + cap
    - คำนวณที่นี่ ส่งต่อให้ทั้ง step 8 และ 9
 8. perkey_rate_limit(user_id, est)            -> 429
 9. resv_id = quota_reserve(user_id, est)      -> 422
10. proxy_to_llm(model_id, messages, cap, req_id, resv_id)
    - on success -> quota_reconcile(resv_id, actual)
    - on failure -> quota_release(resv_id)
    - ทุก failure path เรียก release ผ่าน finally/defer
11. return OpenAI-compatible response
    - choices array ไม่ใช่ message เดี่ยว
    - created เป็น unix timestamp
    - headers: RateLimit-*, X-RateLimit-Tokens-*, X-Request-Id
```

## model_validate(model_name) -> {model_id, max_tokens} | 403

- normalize: trim whitespace
- exact match เท่านั้น ห้าม prefix/substring/fuzzy match
- HGET model:enabled {model_name}
  - hit -> parse and return
  - miss -> query db
    SELECT id, max_tokens, status FROM model WHERE name = $1
    if not found or status != 'enabled' -> 403
    HSET model:enabled ttl 300
    return
- redis down -> query db directly (cheap, low volume)
- model field ไม่มีมา -> 400 ห้ามใช้ DEFAULT_MODEL
- คืน model_id ไม่ใช่ model_name ให้ขั้นถัดไป
  - proxy_to_llm รับ model_id -> ไม่ต้องตรวจซ้ำ
- caller ใช้ max_tokens เป็นเพดาน:
  cap = min(request.max_tokens, model.max_tokens, POLICY_CAP)

## quota_reserve(user_id, est_tokens) -> {ok, resv_id} | 422

- lua atomic:
  now = redis TIME
  ZREMRANGEBYSCORE api:quota:resv:{user_id} -inf (now-300)
  resv = sum(est ที่ parse จาก ZRANGE api:quota:resv:{user_id})
  limit = HGET quota:{user_id} limit
  ไม่มี -> ใช้ default จาก ARGV
  used = HGET quota:{user_id} used (from main app)
  ค่าที่อ่านมาต้องเป็นตัวเลขจำนวนเต็มไม่ติดลบ
  ผิดรูป -> 503 + alert (schema ของแอปหลักเปลี่ยน)
  if used + resv + est > limit -> reject 422
  ZADD api:quota:resv:{user_id} now "{req_id}:{est}"
  EXPIRE api:quota:resv:{user_id} 600
  return req_id
- redis/quota store ไม่พร้อมใช้งาน -> 503 fail closed
  - timeout 2s ไม่ปล่อยค้าง
  - ปลายทางมีต้นทุนจริง การปล่อยผ่านแย่กว่าการปฏิเสธ
  - สอดคล้องกับ fail mode ของทั้งเชน
- ไม่มี field reserved -> ไม่ต้องขอทีมแอปหลัก
- ยอดจองคำนวณสดจากรายการที่ยังไม่หมดอายุ -> ไม่มีอะไรค้าง
- 300s ต้องมากกว่า read timeout อย่างน้อย 2 เท่า
- 422 ไม่บอกยอดคงเหลือ บอกแค่ว่าไม่ผ่าน

## quota_reconcile(resv_id, actual_tokens)

- lua atomic:
  หา member ที่ขึ้นต้นด้วย {req_id} ใน api:quota:resv:{user_id}
  ไม่มี -> หมดอายุแล้ว, log แล้วจบ
  ZREM api:quota:resv:{user_id} member
  HINCRBY quota:{user_id} used +actual
  HINCRBY เป็น atomic ฝั่งเรา
  แต่ atomic ข้ามระบบต้องให้แอปหลักใช้ HINCRBY ด้วย
  ถ้าเขาใช้ SET จะทับยอดของเราหาย -> ต้องยืนยันกับทีม
- actual ต้องผ่าน validate usage จาก proxy_to_llm แล้ว
- เขียน usage_log async:
  source='api', user_id, key_id, amount=actual,
  request_id, timestamp
  - ไม่เก็บ source_ip, prompt content, model
  - ตารางแยกจาก audit_log (ปริมาณต่างกันมาก)
  - retention 60 วัน

## quota_release(resv_id)

- lua atomic:
  ZREM api:quota:resv:{user_id} member
  ไม่มี -> จบ (idempotent)
- เรียกจากทุก failure path ผ่าน finally/defer
- ไม่เขียน usage_log (ไม่ได้หักจริง)

## health check (รันเป็นรอบ)

- อ่าน quota:{user_id} ของ account ทดสอบ
- ตรวจว่า key ยังมีอยู่ และ limit/used ยังเป็นตัวเลข
- ผิดรูป -> alert ทันที
- กัน schema ของแอปหลักเปลี่ยนแล้วเรารู้ตอน production พัง

## proxy_to_llm(model_id, messages, cap_tokens, request_id, resv_id, idem_key?) -> {content, usage} | error

- model_id / resv_id เป็นหลักฐานว่าผ่าน validate + quota แล้ว
  - ประกอบเองไม่ได้ -> เส้นทางที่ข้าม chain เรียกไม่ได้
  - model_id พิสูจน์ว่าเคย lookup สำเร็จ ไม่ได้พิสูจน์ว่ายัง enabled
    - resolve model record จาก model_id ก่อนประกอบ payload
    - status != 'enabled' -> 403
    - ปิดช่วงเวลาระหว่าง validate กับการเรียกจริง
- max concurrent outbound 50 -> เกินแล้ว 503 ทันที
- idempotency (ถ้ามี idem_key):
  - GET idem:{key_id}:{idem_key}
    - hit + payload hash ตรง -> คืน response เดิม ไม่เรียก provider
    - hit + payload hash ต่าง -> 400
    - miss -> เรียกต่อ
- validate messages[].role: system | user | assistant
  - ค่าอื่น -> 400
  - อนุญาต system เพราะ RAG ต้องใช้
- enforce local bounds ก่อนประกอบ payload:
  - cap_tokens = min(cap_tokens, POLICY_CAP)
  - est_input = estimate_tokens(messages)
  - est_input > MAX_INPUT_TOKENS -> 413
  - est_input + cap_tokens > model.context_window -> 400
  - ห้ามส่ง parameter ใดที่ caller กำหนดโดยไม่ผ่าน bound check
- ประกอบ payload เป็น structured object
  - ห้าม string interpolation ของ user input
  - feature นี้ไม่เติม system instruction เอง
- provider credential:
  - โหลดจาก secret store ตอน runtime ไม่ hard-code
  - ไม่เก็บใน global variable ที่ dump ได้
  - ไม่ออกจาก scope ที่ประกอบ HTTP request
  - แยก credential ระหว่าง dev / staging / production
  - รองรับการหมุนเวียนโดยไม่ต้อง restart
- content handling:
  - messages / response ไม่ออกจาก scope ของฟังก์ชันนี้
  - catch แล้วโยน error ใหม่ที่ไม่มี payload ติดไป
  - ไม่มี debug flag สำหรับ log content ใน production
  - loggable allowlist: request_id, key_id, model_id, outcome,
    prompt_tokens, completion_tokens, latency_ms
- outbound call:
  - connect timeout 5s / read timeout 120s
    - timeout -> 503 + quota_release(resv_id)
  - max concurrent outbound 50
  - ไม่ retry อัตโนมัติ
    - ผู้เรียกเป็นคน retry เอง พร้อม Idempotency-Key
    - เหตุผล: ปลายทางคิดเงินต่อการเรียก การ retry เองโดยไม่รู้ว่า
      provider ประมวลผลไปแล้วหรือยัง เสี่ยงจ่ายซ้ำ
    - ถ้าวันหลังเพิ่ม retry ต้องมี: จำกัดจำนวนครั้ง,
      exponential backoff + jitter, และห้าม retry
      การเรียกที่อาจถูกคิดเงินแล้วโดยไม่มี idempotency key
  - circuit breaker: เลื่อนไว้ก่อน
    - timeout + concurrent limit กันเส้นทางหลักได้แล้ว
    - ทบทวนเมื่อมี metric ของ traffic จริง
    - บันทึกเป็นข้อจำกัดที่รู้ตัว ไม่ใช่การมองข้าม
- max response size 10MB -> abort + 502
- ไม่ส่งต่อ provider error body -> แปลงเป็น error กลาง ๆ
  - provider 429 -> 503 ไม่ใช่ 429
- validate usage ก่อนเอาไปหัก quota:
  - field มีอยู่ เป็นจำนวนเต็มบวก
  - total_tokens = prompt_tokens + completion_tokens
  - completion_tokens <= cap_tokens ที่ส่งไป
  - prompt_tokens อยู่ในช่วง ±50% ของค่าประมาณที่คำนวณเอง
  - ผิดข้อใดข้อหนึ่ง -> ใช้ค่าประมาณ (เอนสูงเล็กน้อย) + log discrepancy
- เขียน provider_call_log ทุกครั้งที่เรียก ไม่ว่าสำเร็จหรือไม่
  request_id, key_id, model_id, outcome,
  prompt_tokens, completion_tokens, latency_ms, timestamp
  - เขียนใน finally/defer เช่นเดียวกับ quota_release
  - metadata เท่านั้น
  - retention 60 วัน
- metric: usage validation failure rate
- metric: ค่าเฉลี่ยความห่าง estimate vs actual
- metric: provider call outcome แยกตาม outcome
- metric: concurrent outbound calls, timeout rate
- สำเร็จ + มี idem_key -> SET idem:{key_id}:{idem_key} ttl 300
  - เก็บ response + usage + payload hash

## create_api_key(user_id, name, source_ip) -> {id, key} | error

- mgmt_rate_limit(user_id) -> 429
- validate name: required, 1-100 chars -> 400
- id = ulid()
- secret = csprng(32 base62)
- key_hash = sha256(secret)
- transaction:
  - INSERT api_key (id, user_id, name, key_hash, 'active', now())
    WHERE (SELECT COUNT(*) FROM api_key
    WHERE user_id=$user_id AND status='active') < MAX_KEYS
  - rows_affected = 0 -> rollback, 409
  - INSERT audit_log (actor_id, 'key.created', target_id=id, source_ip, now())
  - audit fails -> rollback, operation fails
- db unavailable -> 503
- return {id, "mthw01_" + id + "_" + secret}
  - secret เป็น local variable เท่านั้น ห้ามผูกกับ entity object
  - response: Cache-Control: no-store
- no cache invalidation needed (key ยังไม่เคยอยู่ใน cache)
- plaintext ไม่ถูกเขียนลงที่ใดนอกจาก response
- last_used_at เป็น NULL ตั้งแต่แรก
  - list_api_keys ใช้ค่านี้แสดงป้าย "Never used"
- double-submit: ยอมรับความเสี่ยง
  - ยิงพร้อมกันสองครั้งได้ key 2 ใบ กิน MAX_KEYS โดยผู้ใช้เห็นใบเดียว
  - ไม่ทำ idempotency เพราะ retry แล้วไม่ได้ secret ซ้ำ
    (แสดงครั้งเดียวตามดีไซน์) ผู้ใช้จะสับสนกว่าเดิม
  - ลดผลกระทบด้วยป้าย "Never used" ในหน้ารายการ
    และปุ่ม discard ใน modal
  - frontend disable ปุ่ม submit ระหว่างรอ response (UX เท่านั้น)
- consent third party: เป็น UX ไม่ใช่ security control
  - checkbox ที่หน้าเว็บไม่ถูกบังคับที่ backend
  - ผู้เรียกที่ยิงตรงสร้าง key ได้โดยไม่เห็นข้อความแจ้ง
  - ยอมรับได้เพราะข้อมูลนี้ระบุไว้ในเอกสาร API ด้วย
    และผู้ที่ยิง API ตรงคือผู้ที่อ่านเอกสารมาแล้ว

## revoke_api_key(user_id, key_id, source_ip) -> ok | 404

- mgmt_rate_limit(user_id) -> 429
- transaction:
  - UPDATE api_key SET status='revoked',
    revoked_at = COALESCE(revoked_at, now())
    WHERE id=$key_id AND user_id=$user_id AND status != 'deleted'
  - rows_affected = 0 -> rollback, 404
  - INSERT audit_log เฉพาะเมื่อ status เดิมเป็น 'active'
    (actor_id, 'key.revoked', target_id, source_ip, now())
- DEL auth:{key_id} from redis
  - retry 3 ครั้ง
  - ยังล้มเหลว -> 500 + alert ห้ามตอบ 200
- idempotent: revoke ซ้ำได้ 200 ไม่ใช่ 404
- owner scoping อยู่ใน query ห้าม SELECT ก่อนแล้วเช็คในโค้ด
- 404 เหมือนกันทุกกรณี: ไม่มี key / key คนอื่น

## delete_api_key(user_id, key_id, source_ip) -> ok | 404

- mgmt_rate_limit(user_id) -> 429
- transaction:
  - UPDATE api_key SET status='deleted', deleted_at=now()
    WHERE id=$key_id AND user_id=$user_id AND status != 'deleted'
  - rows_affected = 0 -> rollback, 404
  - INSERT audit_log (actor_id, 'key.deleted', target_id, source_ip, now())
- DEL auth:{key_id} from redis
  - ล้มเหลว -> 500
- soft delete: row ยังอยู่เพื่อ audit trail
- purge job ลบจริงหลัง 90 วัน
- 404 เหมือนกันทุกกรณี
- ปุ่ม discard ใน create modal เรียก endpoint นี้ ไม่ต้องมี endpoint แยก

## list_api_keys(user_id) -> [{id, name, key_prefix, status, created_at, last_used_at, never_used}]

- mgmt_rate_limit(user_id) -> 429 (read: cap สูงกว่า write)
- WHERE user_id=$user_id AND status != 'deleted'
- ORDER BY created_at DESC
- key_prefix = "mthw01\_" + id (backend ประกอบ frontend ห้ามประกอบเอง)
- never_used = (last_used_at IS NULL)
- serializer allowlist: id, name, key_prefix, status, created_at, last_used_at, never_used
  - key_hash ไม่อยู่ในลิสต์ ป้องกัน ORM serialize ทั้ง entity
- ไม่ส่ง key_hash ไม่ส่ง secret ไม่มี endpoint ดู key ซ้ำ
- ไม่เขียน audit (read operation, เกิดบ่อย)
- response: Cache-Control: no-store (API-wide)

## manage_model(admin_id, model_id, action, source_ip) -> ok | 404

- ตรวจ role = admin ที่นี่ ไม่ใช่แค่ที่ authenticate
- transaction:
  - UPDATE model SET status=$action, updated_at=now()
    WHERE id=$model_id
  - rows_affected = 0 -> rollback, 404
  - INSERT audit_log (actor_id, actor_type='admin',
    'model.enabled' | 'model.disabled', target_id, source_ip, now())
- DEL model:enabled from redis
  - retry 3 ครั้ง
  - ยังล้มเหลว -> 500 + alert
  - ไม่งั้น model ที่ปิดแล้วยังเรียกได้จนกว่า TTL หมด

## Implementation notes

Where the code had to interpret the spec:

- **Where things live.** `routers/chat.py` (HTTP only) → `services/chat.py` (steps
  4–11) → `services/model_catalogue.py`, `services/quota.py`, `services/provider.py`,
  `services/tokens.py`. Steps 0–3 are the `require_api_key` dependency, which runs
  before the body is read.
- **Step 4.** `stream: false` and `n: 1` (what the OpenAI SDKs may send by default)
  are accepted; anything else in `stream`/`n`, and `tools`, `functions`,
  `tool_choice`, `function_call`, or any unknown field, is a 400
  `llm_unsupported_parameter` naming it. Only `model`, `messages`, `max_tokens`,
  `temperature` (0–2) and `top_p` (0–1) reach the provider.
- **model_validate.** The table is `llm_models` (`max_output_tokens`, `status`
  enabled/disabled). Names match with `BINARY` because the collation is
  case-insensitive. The hash TTL is set with `EXPIRE … NX`, so it runs from the
  first fill. Returns a `ValidatedModel` that only this module can build.
- **Quota store.** `quota:{user_id}` belongs to the main app. A missing `used` is
  read as 0 (a new user); a missing `limit` uses `LLM_TOKEN_QUOTA`. `llm_quotas` in
  MySQL is dropped. `quota_reserve` returns a `Reservation` that only this module
  can build — the spec's "resv_id".
- **quota_reconcile of an expired reservation** charges nothing and logs an error, as
  specified. With a 300s window over a 120s read timeout it should never happen.
- **usage_log** is written after reconcile in its own short transaction and is never
  fatal to the response (the call is done and billed). It stores source, key,
  tokens and request id only — no model, IP or content.
- **Model re-check.** `proxy_to_llm` re-reads the model by id from MySQL just before
  the call (a primary-key read in its own session), closing the window between
  validation and the call.
- **Concurrency.** 50 in flight per process, refused with 503 rather than queued.
- **Credentials.** `LLM_API_KEY_FILE` (a mounted secret, one per environment) is read
  on every call, so rotation needs no restart; startup refuses staging/production
  without it. Dev/test may use `LLM_API_KEY` from the environment or `.env`.
- **Usage validation fallback.** Charged = ceil(estimated prompt × 1.1) + the output
  cap sent — the most the call could have cost.
- **Provider status mapping.** 429 and 5xx → 503 `llm_provider_unavailable`; other
  non-200, unparseable bodies and bodies over 10MB → 502 `llm_provider_bad_response`.
  The provider's error body is never forwarded.
- **Idempotency** covers a completed call; two concurrent requests with the same key
  can both reach the provider. Accepted for now: the caller retries after a failure,
  not in parallel.
- **Metrics** (Prometheus, `/metrics`, localhost and the trusted proxy only):
  `llm_provider_calls_total{outcome}`, `llm_usage_validation_failures_total`,
  `llm_prompt_estimate_ratio`, `llm_outbound_in_flight`,
  `llm_outbound_rejected_total`, `llm_idempotent_replays_total`. The timeout rate is
  `llm_provider_calls_total{outcome="timeout"}` over the total.
- **Admin routes.** `POST /v1/admin/models/enable|disable {id}`; `manage_model`
  checks the admin role itself. Audit rows go to `llm_model_audit_logs`.
- **Key management** now has `mgmt_rate_limit`: reads 60 burst / 1 per second,
  writes 10 burst / 10 per minute, per user. Soft-deleted keys are purged 90 days
  after deletion by the retention job.
- **Not built** (not in this spec): `/v1/embeddings` and `/v1/models`.
