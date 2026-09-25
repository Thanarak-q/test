import js from "@eslint/js";
import pluginQuery from "@tanstack/eslint-plugin-query";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import unusedImports from "eslint-plugin-unused-imports";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/routeTree.gen.ts", "src/api/generated"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  // .configs["recommended-latest"] still ships `plugins` as an array of strings,
  // which flat config rejects; the `flat` namespace is the object form.
  reactHooks.configs.flat["recommended-latest"],
  pluginQuery.configs["flat/recommended"],
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "unused-imports": unusedImports },
    rules: {
      "func-style": ["error", "expression"],
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": "off",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
  {
    files: [
      "src/pages/api-keys/**/*.{ts,tsx}",
      "src/stores/demo.ts",
      "src/components/ui/dialog.tsx",
    ],
    rules: {
      "no-restricted-globals": ["error", "localStorage", "sessionStorage", "indexedDB"],
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@nanostores/persistent",
              message: "API key management must not persist secrets or key state.",
            },
          ],
        },
      ],
      "no-restricted-properties": [
        "error",
        {
          object: "document",
          property: "cookie",
          message: "API key management must not use document.cookie.",
        },
        {
          object: "window",
          property: "localStorage",
          message: "API key management must not use browser storage.",
        },
        {
          object: "window",
          property: "sessionStorage",
          message: "API key management must not use browser storage.",
        },
        {
          object: "window",
          property: "indexedDB",
          message: "API key management must not use browser storage.",
        },
        {
          object: "globalThis",
          property: "localStorage",
          message: "API key management must not use browser storage.",
        },
        {
          object: "globalThis",
          property: "sessionStorage",
          message: "API key management must not use browser storage.",
        },
        {
          object: "globalThis",
          property: "indexedDB",
          message: "API key management must not use browser storage.",
        },
      ],
    },
  },
  { files: ["src/components/ui/**"], rules: { "func-style": "off" } },
  prettier,
);
