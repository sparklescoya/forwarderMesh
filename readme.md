# ForwarderMesh

Quart app for registering service workers with their urls, ids and scopes (scopes: receive and/or request).

## Routes

### Register Service  `POST`
`/register`

**Body**:
```json
{
  "id": "service-id",
  "url": "http://service-url",
  "scopes": ["request", "receive"] 
}
```

**Response (201)**:
```json
{
  "message": "Service registered successfully",
  "id": "service-id"
}
```

### Get Service Details `GET`
`/get/<id>`

**Response (200)**:
```json
{
  "id": "service-id",
  "url": "http://service-url",
  "scopes": ["request", "receive"] 
}
```

### Proxy Request `ANY` (GET, POST, PUT, DELETE, PATCH)
`/request/<id>/<relativepath>`

**Headers**:
- `X-Service-ID`: `<caller_service_id>` (Required)

**Requirements**:
- Caller must be registered and have `request` scope.
- Target service must be registered and have `receive` scope.

**Response**:
- Returns the response from the upstream service.
- **Errors**:
  - 401: Unauthorized (Missing header)
  - 403: Forbidden (Missing scopes or registration)
  - 404: Service not found
  - 502: Upstream error