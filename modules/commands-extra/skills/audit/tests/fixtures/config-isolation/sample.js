// Config isolation fixture -- sample JS file for eslint to scan.
// This file is intentionally minimal. The test is whether the .eslintrc.js
// in this same directory gets loaded (it should NOT, due to --no-config-lookup).
eval("hello"); // This would trigger no-eval if config isolation works correctly.
