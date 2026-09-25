# Nginx Request Fields

| Flow                              | Fields ที่ต้องการจาก Nginx              |
| --------------------------------- | --------------------------------------- |
| Require HTTPS                     | `X-Forwarded-Proto`                     |
| Pre-auth rate limit               | `X-Real-IP`                             |
| Pre-auth rate limit fallback      | `X-Forwarded-For` ใช้ค่าขวาสุด          |
| Pre-auth rate limit validation    | `request.client.host` เป็น IP ของ Nginx |
| Pre-auth rate limit configuration | `trusted_proxy_ips` รายการ IP ของ Nginx |
