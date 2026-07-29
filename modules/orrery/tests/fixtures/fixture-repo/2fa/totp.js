// numeric-leading top-level dir: area id must sanitize 2fa -> a_2fa
exports.totp = function totp(seed) { return String(seed).slice(0, 6) }
