from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

#Password hashing context... uses bcrypt algorithm
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

#JWT settings
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  #24 hours


#Hash a plain password
def hash_password(password: str) -> str:
    #Truncate to 72 bytes to avoid bcrypt limit
    password = password[:72]
    return pwd_context.hash(password)


#Verify a plain password against a hashed one
def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_password = plain_password[:72]
    return pwd_context.verify(plain_password, hashed_password)


#Create a JWT access token
def create_access_token(learner_id: int) -> str:
    #Token expires after ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    #Data to encode in the token
    payload = {
        "sub": str(learner_id),  #sub = subject = who this token belongs to
        "exp": expire            #exp = expiration time
    }

    #Create and sign the token with the secret key
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


#Decode and verify a JWT token to returns learner_id
def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        learner_id = int(payload.get("sub"))
        return learner_id
    except JWTError:
        return None