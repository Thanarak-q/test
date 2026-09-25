// Code samples for the docs, built from values.ts so no value is spelled out
// twice. Never put a real key in a sample: examples always use the
// placeholder below, so no secret reaches the DOM, clipboard or screenshots.
import { isPlaceholder, listPlaceholders } from "./placeholders";
import { docsValues } from "./values";

type Language = "curl" | "python" | "javascript";

export type Sample = {
  code: Partial<Record<Language, string>>;
  // Shows the "To be confirmed" badge on the code block when the sample
  // depends on a value that is still a placeholder.
  unconfirmed: boolean;
};

export type Snippet = { code: string; unconfirmed: boolean };

const { baseUrl, keyPrefix } = docsValues;
const chatModel = docsValues.models.find((model) => model.purpose === "chat")!;
const embeddingModel = docsValues.models.find((model) => model.purpose === "embedding")!;

export const exampleKey = `${keyPrefix}_YOUR_KEY_ID_YOUR_SECRET`;

const dependsOn = (...values: unknown[]) =>
  values.some((value) =>
    typeof value === "object" ? listPlaceholders(value).length > 0 : isPlaceholder(value, ""),
  );

const urlPending = dependsOn(baseUrl);
const chatPending = urlPending || dependsOn(chatModel);
const embeddingPending = urlPending || dependsOn(embeddingModel);

// region Quickstart / chat
export const chatRequest: Sample = {
  unconfirmed: chatPending,
  code: {
    curl: `curl ${baseUrl}/chat/completions \\
  -H "Authorization: Bearer $MATHEW_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${chatModel.name}",
    "messages": [{"role": "user", "content": "Say hello in Thai."}]
  }'`,
    python: `import os
from openai import OpenAI

client = OpenAI(
    base_url="${baseUrl}",
    api_key=os.environ["MATHEW_API_KEY"],  # ${exampleKey}
)

response = client.chat.completions.create(
    model="${chatModel.name}",
    messages=[{"role": "user", "content": "Say hello in Thai."}],
)
print(response.choices[0].message.content)`,
    javascript: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${baseUrl}",
  apiKey: process.env.MATHEW_API_KEY, // ${exampleKey}
});

const response = await client.chat.completions.create({
  model: "${chatModel.name}",
  messages: [{ role: "user", content: "Say hello in Thai." }],
});
console.log(response.choices[0].message.content);`,
  },
};

export const chatResponse: Snippet = {
  unconfirmed: dependsOn(chatModel),
  code: `{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1790000000,
  "model": "${chatModel.name}",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "สวัสดี" },
      "finish_reason": "stop"
    }
  ],
  "usage": { "prompt_tokens": 14, "completion_tokens": 3, "total_tokens": 17 }
}`,
};

export const chatRequestSchema: Snippet = {
  unconfirmed: false,
  code: `{
  "model": string,            // a chat model from the Models page
  "messages": [               // the conversation so far, oldest first
    { "role": "system" | "user" | "assistant", "content": string }
  ],
  "max_tokens": integer,      // optional: cap on the reply's length
  "temperature": number       // optional, 0 to 2
}`,
};

export const chatResponseSchema: Snippet = {
  unconfirmed: false,
  code: `{
  "id": string,
  "object": "chat.completion",
  "created": integer,         // Unix seconds
  "model": string,
  "choices": [
    {
      "index": integer,
      "message": { "role": "assistant", "content": string },
      "finish_reason": "stop" | "length"
    }
  ],
  "usage": { "prompt_tokens": integer, "completion_tokens": integer, "total_tokens": integer }
}`,
};
// endregion

// region Embeddings
export const embeddingsRequest: Sample = {
  unconfirmed: embeddingPending,
  code: {
    curl: `curl ${baseUrl}/embeddings \\
  -H "Authorization: Bearer $MATHEW_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${embeddingModel.name}", "input": "The quick brown fox"}'`,
    python: `response = client.embeddings.create(
    model="${embeddingModel.name}",
    input="The quick brown fox",
)
vector = response.data[0].embedding`,
    javascript: `const response = await client.embeddings.create({
  model: "${embeddingModel.name}",
  input: "The quick brown fox",
});
const vector = response.data[0].embedding;`,
  },
};

export const embeddingsSchema: Snippet = {
  unconfirmed: false,
  code: `// request
{
  "model": string,            // an embedding model from the Models page
  "input": string | string[]
}

// response
{
  "object": "list",
  "data": [{ "object": "embedding", "index": integer, "embedding": number[] }],
  "model": string,
  "usage": { "prompt_tokens": integer, "total_tokens": integer }
}`,
};
// endregion

// region Models
export const modelsRequest: Sample = {
  unconfirmed: urlPending,
  code: {
    curl: `curl ${baseUrl}/models \\
  -H "Authorization: Bearer $MATHEW_API_KEY"`,
    python: `for model in client.models.list():
    print(model.id)`,
    javascript: `for await (const model of client.models.list()) {
  console.log(model.id);
}`,
  },
};

export const modelsResponse: Snippet = {
  unconfirmed: docsValues.models.some((model) => dependsOn(model)),
  code: `{
  "object": "list",
  "data": [
${docsValues.models
  .map((model) => `    { "id": "${model.name}", "object": "model", "owned_by": "mathew" }`)
  .join(",\n")}
  ]
}`,
};
// endregion

// region Authentication
export const authHeader: Snippet = {
  unconfirmed: false,
  code: `Authorization: Bearer ${exampleKey}`,
};

export const envVariable: Sample = {
  unconfirmed: false,
  code: {
    curl: `# .env — list this file in .gitignore
MATHEW_API_KEY=${exampleKey}`,
    python: `import os

api_key = os.environ["MATHEW_API_KEY"]  # fails loudly if it is missing`,
    javascript: `const apiKey = process.env.MATHEW_API_KEY;
if (!apiKey) throw new Error("MATHEW_API_KEY is not set");`,
  },
};
// endregion

// region Errors and rate limits
export const errorResponse: Snippet = {
  unconfirmed: false,
  code: `HTTP/1.1 429 Too Many Requests
Retry-After: 4
X-Request-Id: 9f2c4e1a7b3d4c5e8f901a2b3c4d5e6f

{
  "success": false,
  "data": null,
  "error": {
    "code": "rate_limit_exceeded_tokens",
    "message": "Too many tokens. Retry in 4s."
  },
  "meta": null
}`,
};

export const backoff: Sample = {
  unconfirmed: false,
  code: {
    python: `import random
import time


def call_with_backoff(send, attempts=5):
    """Retry 429 and 503, honouring Retry-After. Never retry 401: it will not fix itself."""
    for attempt in range(attempts):
        response = send()
        if response.status_code not in (429, 503):
            return response
        code = response.json().get("error", {}).get("code", "")
        if code == "rate_limit_exceeded_tokens":
            # Waiting helps, but so does sending less: shorten the prompt or max_tokens.
            pass
        wait = float(response.headers.get("Retry-After", 2**attempt))
        time.sleep(wait + random.uniform(0, 0.5))  # jitter spreads retries out
    return response`,
    javascript: `const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Retry 429 and 503, honouring Retry-After. Never retry 401: it will not fix itself.
export const callWithBackoff = async (send, attempts = 5) => {
  let response;
  for (let attempt = 0; attempt < attempts; attempt++) {
    response = await send();
    if (response.status !== 429 && response.status !== 503) return response;
    const body = await response.clone().json().catch(() => ({}));
    if (body.error?.code === "rate_limit_exceeded_tokens") {
      // Waiting helps, but so does sending less: shorten the prompt or max_tokens.
    }
    const retryAfter = Number(response.headers.get("Retry-After")) || 2 ** attempt;
    await sleep((retryAfter + Math.random() * 0.5) * 1000); // jitter
  }
  return response;
};`,
  },
};
// endregion

// region Migrate from OpenAI
export const migrate: Sample = {
  unconfirmed: chatPending,
  code: {
    python: `client = OpenAI(
-   api_key=os.environ["OPENAI_API_KEY"],
+   base_url="${baseUrl}",
+   api_key=os.environ["MATHEW_API_KEY"],
)

response = client.chat.completions.create(
-   model="gpt-4o",
+   model="${chatModel.name}",
    messages=messages,
)`,
    javascript: `const client = new OpenAI({
-  apiKey: process.env.OPENAI_API_KEY,
+  baseURL: "${baseUrl}",
+  apiKey: process.env.MATHEW_API_KEY,
});

const response = await client.chat.completions.create({
-  model: "gpt-4o",
+  model: "${chatModel.name}",
   messages,
});`,
  },
};
// endregion

// region Security
export const escaping: Sample = {
  unconfirmed: false,
  code: {
    javascript: `// Model output is untrusted: it can contain markup copied from the prompt.
const output = response.choices[0].message.content;

// Wrong: parses the output as HTML, so <img src=x onerror=...> runs.
// element.innerHTML = output;

// Right: inserted as text, never parsed.
element.textContent = output;

// In React, {output} in JSX is escaped for you. Never pass it to
// dangerouslySetInnerHTML without a sanitizer such as DOMPurify.`,
    python: `import html

output = response.choices[0].message.content

# Wrong: f"<p>{output}</p>" puts raw model output into your page.
# Right: escape before it goes into HTML.
safe = f"<p>{html.escape(output)}</p>"

# Template engines such as Jinja2 escape by default when autoescape is on;
# never mark model output as |safe.`,
  },
};
// endregion
