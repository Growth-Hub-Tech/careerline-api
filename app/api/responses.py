#Error responses shown in Swagger (/docs).
#FastAPI only lists 200 and 422 by itself, so the other codes showed as "Undocumented".
ERRORS = {
    400: {"description": "Bad request: invalid input (the detail says what is wrong)"},
    401: {"description": "Not logged in: missing, invalid or expired token"},
    403: {"description": "Not allowed: this belongs to another learner"},
    404: {"description": "Not found"},
    409: {"description": "Conflict: this attempt was already submitted"},
    410: {"description": "Gone: this old route is retired (see detail for the new one)"},
}


#Pick the codes a route can return, e.g. responses=errors(401, 403, 404)
def errors(*codes):
    return {code: ERRORS[code] for code in codes}
