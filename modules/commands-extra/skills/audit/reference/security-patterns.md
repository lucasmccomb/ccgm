# Security Audit Patterns

Reference patterns for the security audit agent. Based on OWASP Top 10, gitleaks patterns, and common vulnerability categories.

## 1. Hardcoded Secrets

### Patterns to Search For

```regex
# API Keys
(api[_-]?key|apikey)['":\s]*[=:]\s*['"][a-zA-Z0-9_\-]{20,}['"]
(sk-[a-zA-Z0-9]{48})  # OpenAI keys
(ghp_[a-zA-Z0-9]{36})  # GitHub personal tokens
(gho_[a-zA-Z0-9]{36})  # GitHub OAuth tokens
(github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59})  # GitHub fine-grained tokens

# AWS
(AKIA[0-9A-Z]{16})  # AWS Access Key ID
aws[_-]?secret[_-]?access[_-]?key

# Database URLs
(postgres|mysql|mongodb)://[^:]+:[^@]+@

# Generic secrets
(password|passwd|pwd|secret|token|auth)['":\s]*[=:]\s*['"][^'"]{8,}['"]
(private[_-]?key|privatekey)
-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----
```

### Common File Locations
- `.env` files committed to repo
- `config/*.json` with hardcoded values
- Test files with real credentials
- Docker compose files with passwords
- CI/CD configs with embedded secrets

## 2. Injection Vulnerabilities

### SQL Injection
```javascript
// DANGEROUS - String concatenation
query(`SELECT * FROM users WHERE id = ${userId}`)
query("SELECT * FROM users WHERE name = '" + name + "'")

// SAFE - Parameterized queries
query('SELECT * FROM users WHERE id = $1', [userId])
```

### Command Injection
```javascript
// DANGEROUS - User input in shell commands
exec(`ls ${userInput}`)
spawn('bash', ['-c', userInput])
child_process.execSync(userInput)

// SAFE - Whitelist approach or avoid shell
execFile('ls', [sanitizedPath])
```

### XSS (Cross-Site Scripting)
```jsx
// DANGEROUS
<div dangerouslySetInnerHTML={{ __html: userContent }} />
element.innerHTML = userInput
document.write(userInput)

// SAFE
<div>{userContent}</div>  // React auto-escapes
import DOMPurify from 'dompurify'
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content) }} />
```

## 3. Authentication Issues

### Patterns to Flag
- Passwords stored in plain text
- Missing password hashing (bcrypt, argon2)
- Weak JWT secrets (short strings, common words)
- JWT stored in localStorage (vulnerable to XSS)
- Missing token expiration
- Session tokens in URLs
- Hardcoded admin credentials

### Secure Patterns
```javascript
// Password hashing
import bcrypt from 'bcrypt'
const hash = await bcrypt.hash(password, 12)

// JWT with proper secret
const secret = process.env.JWT_SECRET  // From env, not hardcoded
jwt.sign(payload, secret, { expiresIn: '1h' })

// Secure cookie storage
res.cookie('token', token, {
  httpOnly: true,
  secure: true,
  sameSite: 'strict'
})
```

## 4. Insecure Configuration

### Patterns to Flag
- `DEBUG=true` or `NODE_ENV=development` in production configs
- CORS with `origin: '*'`
- Missing rate limiting on auth endpoints
- Verbose error messages exposing stack traces
- Default/weak credentials in configs
- Disabled security headers

### Expected Security Headers
```javascript
// helmet.js or manual headers
'Content-Security-Policy'
'X-Content-Type-Options: nosniff'
'X-Frame-Options: DENY'
'Strict-Transport-Security'
```

## 5. Cryptography Issues

### Weak Algorithms (Flag These)
- MD5 for password hashing
- SHA1 for security purposes
- DES encryption
- ECB mode encryption
- Random without crypto (Math.random for security)

### Secure Alternatives
```javascript
// Use crypto.randomBytes, not Math.random
import crypto from 'crypto'
const token = crypto.randomBytes(32).toString('hex')

// Use bcrypt/argon2, not MD5/SHA1 for passwords
import argon2 from 'argon2'
const hash = await argon2.hash(password)
```

## 6. Data Exposure

### Patterns to Flag
- Logging sensitive data (passwords, tokens, PII)
- Returning full user objects with passwords
- Stack traces in API responses
- Sensitive data in URL parameters
- Unencrypted sensitive data in database

### Sensitive Fields to Watch
```
password, passwd, pwd, secret, token, apiKey, api_key,
ssn, social_security, credit_card, creditCard, cvv,
private_key, privateKey, auth_token, authToken,
refresh_token, refreshToken, session_id, sessionId
```

## 7. OWASP Top 10 Quick Reference

| Category | What to Look For |
|----------|------------------|
| A01 Broken Access Control | Missing auth checks, IDOR vulnerabilities |
| A02 Cryptographic Failures | Weak encryption, exposed secrets |
| A03 Injection | SQL, command, XSS injection points |
| A04 Insecure Design | Missing security in architecture |
| A05 Security Misconfiguration | Default configs, verbose errors |
| A06 Vulnerable Components | Outdated dependencies with CVEs |
| A07 Auth Failures | Weak passwords, missing MFA |
| A08 Data Integrity Failures | Missing signature verification |
| A09 Logging Failures | Missing audit logs, logging secrets |
| A10 SSRF | Unvalidated URL fetching |

## Severity Guidelines

| Severity | Criteria |
|----------|----------|
| **Critical** | Hardcoded production secrets, SQL injection, RCE |
| **High** | XSS, auth bypass, sensitive data exposure |
| **Medium** | Weak crypto, missing security headers, verbose errors |
| **Low** | Minor config issues, potential but unexploitable |
