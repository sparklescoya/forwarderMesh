# Quart app for registering service workers with their urls, ids and scopes (scopes: receive and/or request)
## Routes:
`/register` - POST - Register a new service worker (url, id, scopes)

`/get/<id>` - GET - Check data of a registered service by id

`/request/<id>/<relativepath>` - ANY - Make a request of any method to the service url by id