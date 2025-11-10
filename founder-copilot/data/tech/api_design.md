# API Design Best Practices

## RESTful API Principles

### Resource-Based URLs
- **Nouns, not verbs** - `/users` not `/getUsers`
- **Hierarchical** - `/users/123/posts/456`
- **Plural nouns** - `/users` not `/user`
- **Clear structure** - Predictable URL patterns

### HTTP Methods
- **GET** - Retrieve resource (idempotent, safe)
- **POST** - Create resource (not idempotent)
- **PUT** - Update/replace resource (idempotent)
- **PATCH** - Partial update (idempotent)
- **DELETE** - Remove resource (idempotent)

### Status Codes
- **200 OK** - Successful GET, PUT, PATCH
- **201 Created** - Successful POST
- **204 No Content** - Successful DELETE
- **400 Bad Request** - Invalid request
- **401 Unauthorized** - Authentication required
- **403 Forbidden** - Not authorized
- **404 Not Found** - Resource doesn't exist
- **429 Too Many Requests** - Rate limit exceeded
- **500 Internal Server Error** - Server error

## API Versioning

### URL Versioning
- **Path-based** - `/v1/users`, `/v2/users`
- **Pros**: Clear, explicit
- **Cons**: URL clutter
- **Example**: `api.example.com/v1/users`

### Header Versioning
- **Accept header** - `Accept: application/vnd.api+json;version=1`
- **Pros**: Clean URLs
- **Cons**: Less discoverable
- **Example**: Custom header `API-Version: 1`

### Query Parameter
- **Version in query** - `/users?version=1`
- **Pros**: Simple
- **Cons**: Not RESTful, easy to forget
- **Not recommended** for production

**Recommendation**: Use URL versioning (`/v1/`, `/v2/`) for clarity

## Request/Response Design

### Request Headers
- **Authorization** - `Bearer <token>` or `Basic <credentials>`
- **Content-Type** - `application/json`
- **Accept** - What response format client wants
- **User-Agent** - Client identification

### Request Body
- **JSON format** - Standard, easy to parse
- **Validate input** - Required fields, types, formats
- **Error messages** - Clear, actionable
- **Example**:
```json
{
  "email": "user@example.com",
  "name": "John Doe",
  "age": 30
}
```

### Response Format
- **Consistent structure** - Same format across endpoints
- **Include metadata** - Pagination, timestamps, version
- **Error format** - Consistent error structure
- **Example**:
```json
{
  "data": { ... },
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 100
  }
}
```

## Error Handling

### Error Response Structure
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Email is required",
    "field": "email",
    "details": { ... }
  }
}
```

### Error Codes
- **Use codes, not just messages** - Easier to handle programmatically
- **Consistent codes** - Same error = same code
- **Document codes** - API documentation lists all codes
- **Examples**: `VALIDATION_ERROR`, `NOT_FOUND`, `UNAUTHORIZED`

### Validation Errors
- **Return all errors** - Don't stop at first error
- **Field-level errors** - Which field, what's wrong
- **Clear messages** - "Email must be valid format" not "Invalid input"

## Pagination

### Offset-Based Pagination
- **Query params** - `?page=1&per_page=20`
- **Pros**: Simple, easy to implement
- **Cons**: Performance issues with large offsets
- **When**: Small datasets, simple use cases

### Cursor-Based Pagination
- **Cursor token** - `?cursor=abc123&limit=20`
- **Pros**: Better performance, consistent results
- **Cons**: More complex, can't jump to page
- **When**: Large datasets, real-time data

### Response Format
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 100,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  }
}
```

## Filtering, Sorting, Searching

### Filtering
- **Query parameters** - `?status=active&role=admin`
- **Operators** - `?age[gte]=18&age[lte]=65`
- **Multiple values** - `?tags=python,javascript`
- **Document operators** - Clear API docs on supported filters

### Sorting
- **Sort parameter** - `?sort=created_at:desc`
- **Multiple fields** - `?sort=name:asc,created_at:desc`
- **Default sort** - Consistent default (e.g., `created_at:desc`)

### Searching
- **Search parameter** - `?q=keyword`
- **Full-text search** - Use search engine (Elasticsearch)
- **Scope** - Which fields are searchable
- **Fuzzy matching** - Handle typos, variations

## Rate Limiting

### Headers
- **X-RateLimit-Limit** - Requests allowed per window
- **X-RateLimit-Remaining** - Requests remaining
- **X-RateLimit-Reset** - When limit resets (timestamp)

### Strategies
- **Per API key** - Different limits per key tier
- **Per IP** - Prevent abuse
- **Per user** - Fair usage
- **Sliding window** - More accurate than fixed window

### Response
- **429 status code** - Too Many Requests
- **Retry-After header** - Seconds to wait before retry
- **Clear error message** - "Rate limit exceeded. Try again in 60 seconds."

## Authentication & Authorization

### API Keys
- **Header** - `X-API-Key: <key>`
- **Query param** - `?api_key=<key>` (less secure)
- **When**: Service-to-service, simple use cases
- **Store securely** - Never commit to code

### OAuth 2.0
- **Bearer tokens** - `Authorization: Bearer <token>`
- **Refresh tokens** - Long-lived refresh, short-lived access
- **Scopes** - Fine-grained permissions
- **When**: User-facing APIs, third-party integrations

### JWT Tokens
- **Stateless** - No server-side session storage
- **Self-contained** - User info in token
- **Expiration** - Built-in expiry
- **When**: Microservices, distributed systems

## Documentation

### OpenAPI/Swagger
- **Standard format** - Machine-readable API spec
- **Interactive docs** - Try API in browser
- **Code generation** - Generate client SDKs
- **Tools**: Swagger UI, ReDoc, Stoplight

### Documentation Best Practices
- **Getting started guide** - Quick start tutorial
- **Authentication** - How to authenticate
- **Endpoints** - All endpoints with examples
- **Error codes** - List of all error codes
- **Rate limits** - Limits and policies
- **Changelog** - Version history, breaking changes

## Performance

### Response Time
- **Target**: < 200ms for simple queries
- **Optimize slow endpoints** - Database queries, external calls
- **Caching** - Cache frequently accessed data
- **Compression** - Gzip responses

### Payload Size
- **Minimize response** - Only return needed fields
- **Field selection** - `?fields=id,name,email`
- **Pagination** - Don't return all records
- **Compression** - Gzip large responses

### Caching
- **Cache headers** - `Cache-Control: public, max-age=3600`
- **ETags** - Conditional requests, 304 Not Modified
- **CDN** - Cache static responses at edge

## Security

### HTTPS Only
- **Always use HTTPS** - Never HTTP in production
- **Redirect HTTP** - Automatically redirect to HTTPS
- **HSTS header** - Force HTTPS in browser

### Input Validation
- **Validate all inputs** - Never trust client data
- **Sanitize** - Prevent injection attacks
- **Type checking** - Ensure correct data types
- **Size limits** - Prevent DoS attacks

### CORS
- **Configure properly** - Only allow trusted origins
- **Credentials** - Handle cookies/auth carefully
- **Preflight** - Handle OPTIONS requests

## Common Mistakes

1. **Inconsistent naming** - `user_id` vs `userId` vs `userId`
2. **No versioning** - Breaking changes without version
3. **Poor error messages** - "Error" not helpful
4. **No rate limiting** - Vulnerable to abuse
5. **Over-fetching** - Returning too much data
6. **No documentation** - Developers can't use API
7. **Insecure** - No authentication, HTTP only
8. **No pagination** - Returning all records

