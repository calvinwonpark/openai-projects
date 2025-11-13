# Security Best Practices for Startups

## Authentication & Authorization

### Password Security
- **Hashing, not encryption** - Use bcrypt, Argon2, scrypt
- **Salt passwords** - Unique salt per password
- **Minimum length** - 8+ characters, enforce complexity
- **Password reset** - Secure token, time-limited
- **Never store plaintext** - Even in logs or debugging

### Multi-Factor Authentication (MFA)
- **Enable MFA** - For admin accounts, sensitive operations
- **TOTP** - Time-based one-time passwords (Google Authenticator)
- **SMS/Email** - Less secure but better than nothing
- **Backup codes** - Provide recovery codes

### Session Management
- **Secure cookies** - HttpOnly, Secure, SameSite flags
- **Session timeout** - Expire after inactivity
- **Token expiration** - Short-lived access tokens
- **Refresh tokens** - Long-lived, stored securely

## Data Protection

### Encryption
- **At rest** - Encrypt databases, file storage
- **In transit** - HTTPS/TLS for all connections
- **Key management** - Use key management services (AWS KMS, HashiCorp Vault)
- **Never commit secrets** - Use environment variables, secret managers

### PII (Personally Identifiable Information)
- **Minimize collection** - Only collect what you need
- **Encrypt sensitive data** - Email, phone, SSN, credit cards
- **Access controls** - Limit who can access PII
- **Data retention** - Delete data when no longer needed
- **GDPR/CCPA compliance** - Right to access, delete, portability

### Database Security
- **Least privilege** - Database users with minimal permissions
- **Parameterized queries** - Prevent SQL injection
- **Connection encryption** - TLS for database connections
- **Backup encryption** - Encrypt database backups
- **Regular updates** - Patch database software

## API Security

### Input Validation
- **Validate all inputs** - Never trust client data
- **Sanitize** - Remove dangerous characters
- **Type checking** - Ensure correct data types
- **Size limits** - Prevent DoS attacks
- **Whitelist, don't blacklist** - Allow only known good inputs

### Rate Limiting
- **Prevent abuse** - Limit requests per IP/user
- **DDoS protection** - Cloudflare, AWS Shield
- **API key limits** - Different tiers, different limits
- **Exponential backoff** - For retries

### CORS (Cross-Origin Resource Sharing)
- **Configure properly** - Only allow trusted origins
- **Credentials** - Handle cookies/auth carefully
- **Preflight requests** - Handle OPTIONS requests
- **Don't use wildcard** - `*` allows any origin

## Infrastructure Security

### Cloud Security
- **IAM roles** - Least privilege principle
- **Security groups** - Restrict network access
- **VPC** - Isolate resources in private network
- **Encryption** - Enable encryption for storage, databases
- **Backup security** - Encrypt backups, test restores

### Secrets Management
- **Never commit secrets** - Use .gitignore, secret scanners
- **Environment variables** - For local development
- **Secret managers** - AWS Secrets Manager, HashiCorp Vault
- **Rotate secrets** - Regular rotation of API keys, passwords
- **Separate environments** - Different secrets for dev/staging/prod

### Container Security
- **Base images** - Use official, minimal images
- **Scan images** - For vulnerabilities (Trivy, Snyk)
- **Non-root user** - Don't run containers as root
- **Secrets** - Don't bake secrets into images
- **Updates** - Keep base images updated

## Application Security

### Dependency Management
- **Keep dependencies updated** - Regular security updates
- **Vulnerability scanning** - npm audit, pip check, Snyk
- **Minimize dependencies** - Fewer dependencies = smaller attack surface
- **Lock files** - package-lock.json, requirements.txt with versions

### Code Security
- **Code reviews** - Security-focused reviews
- **Static analysis** - SonarQube, CodeQL, Semgrep
- **Secure coding practices** - OWASP Top 10 awareness
- **Input validation** - Validate and sanitize all inputs
- **Error handling** - Don't leak sensitive info in errors

### Logging & Monitoring
- **Don't log secrets** - No passwords, tokens, API keys
- **Sanitize logs** - Remove PII from logs
- **Monitor for attacks** - Failed logins, unusual patterns
- **Alert on anomalies** - Automated security alerts
- **Audit logs** - Track who did what, when

## Common Vulnerabilities (OWASP Top 10)

### Injection Attacks
- **SQL Injection** - Use parameterized queries
- **NoSQL Injection** - Validate input, use ORM
- **Command Injection** - Don't execute user input
- **Prevention**: Input validation, parameterized queries, least privilege

### Broken Authentication
- **Weak passwords** - Enforce strong passwords
- **Session fixation** - Regenerate session ID on login
- **Credential stuffing** - Rate limiting, MFA
- **Prevention**: Strong authentication, secure sessions, MFA

### Sensitive Data Exposure
- **Encryption** - Encrypt sensitive data at rest and in transit
- **No sensitive data in URLs** - Use POST, not GET
- **Secure storage** - Use secure storage services
- **Prevention**: Encryption, secure storage, no exposure

### XML External Entities (XXE)
- **Disable XXE** - In XML parsers
- **Use JSON** - Prefer JSON over XML
- **Validate XML** - Use safe parsers
- **Prevention**: Disable XXE, use safe parsers

### Broken Access Control
- **Authorization checks** - Verify permissions on every request
- **IDOR** - Don't expose internal IDs, use UUIDs
- **Role-based access** - Implement RBAC
- **Prevention**: Authorization on every endpoint, test thoroughly

### Security Misconfiguration
- **Default credentials** - Change all defaults
- **Error messages** - Don't leak stack traces
- **Unnecessary features** - Disable unused features
- **Prevention**: Security hardening, regular audits

### XSS (Cross-Site Scripting)
- **Output encoding** - Encode user input in HTML
- **CSP** - Content Security Policy headers
- **Sanitize** - Sanitize user-generated content
- **Prevention**: Output encoding, CSP, sanitization

### Insecure Deserialization
- **Don't deserialize untrusted data** - Validate before deserializing
- **Use safe formats** - JSON instead of binary formats
- **Sign data** - Verify integrity
- **Prevention**: Validate, use safe formats, sign data

### Using Components with Known Vulnerabilities
- **Dependency scanning** - Regular vulnerability scans
- **Keep updated** - Update dependencies regularly
- **Minimize dependencies** - Fewer dependencies = less risk
- **Prevention**: Regular updates, vulnerability scanning

### Insufficient Logging & Monitoring
- **Log security events** - Failed logins, privilege changes
- **Monitor** - Real-time monitoring and alerting
- **Incident response** - Plan for security incidents
- **Prevention**: Comprehensive logging, monitoring, incident response

## Compliance

### GDPR (EU)
- **Right to access** - Users can request their data
- **Right to deletion** - Users can request data deletion
- **Data portability** - Export user data
- **Privacy by design** - Build privacy into product
- **Data protection officer** - For large organizations

### CCPA (California)
- **Right to know** - What data is collected
- **Right to delete** - Request data deletion
- **Right to opt-out** - Opt-out of data sales
- **Non-discrimination** - Can't discriminate for exercising rights

### SOC 2
- **Security controls** - Documented security practices
- **Regular audits** - Annual security audits
- **Access controls** - Who has access to what
- **Monitoring** - Security monitoring and alerting

## Incident Response

### Preparation
- **Incident response plan** - Documented procedures
- **Team roles** - Who does what in incident
- **Communication plan** - How to notify stakeholders
- **Backup and recovery** - Test restore procedures

### Detection
- **Monitoring** - Real-time security monitoring
- **Alerts** - Automated security alerts
- **Log analysis** - Regular log review
- **Threat intelligence** - Stay informed about threats

### Response
- **Contain** - Isolate affected systems
- **Investigate** - Understand scope and impact
- **Remediate** - Fix vulnerabilities, remove threats
- **Communicate** - Notify affected users if required
- **Document** - Post-incident review and documentation

## Security Checklist

### Development
- [ ] Input validation on all inputs
- [ ] Parameterized queries (no SQL injection)
- [ ] Output encoding (prevent XSS)
- [ ] Authentication and authorization
- [ ] Secure password storage (hashing)
- [ ] HTTPS everywhere
- [ ] Secrets management (no hardcoded secrets)
- [ ] Dependency scanning
- [ ] Security headers (CSP, HSTS, etc.)

### Infrastructure
- [ ] Encrypted databases and storage
- [ ] Secure network configuration
- [ ] Least privilege access (IAM)
- [ ] Regular security updates
- [ ] Backup and disaster recovery
- [ ] Monitoring and alerting
- [ ] Logging (without secrets)

### Operations
- [ ] Security monitoring
- [ ] Incident response plan
- [ ] Regular security audits
- [ ] Employee security training
- [ ] Access reviews
- [ ] Compliance (GDPR, CCPA if applicable)

