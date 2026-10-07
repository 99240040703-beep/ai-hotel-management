from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import User, Customer
    from schemas import RegisterRequest, LoginRequest
    from utils.security import create_access_token
    from middleware.auth import require_current_user
except (ImportError, ValueError):
    from ..database import get_db
    from ..models import User, Customer
    from ..schemas import RegisterRequest, LoginRequest
    from ..utils.security import create_access_token
    from ..middleware.auth import require_current_user


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# ============================================================
# PASSWORD FUNCTIONS
# ============================================================

def verify_password(
    plain_password: str,
    hashed_password: str,
):
    return pwd_context.verify(
        plain_password,
        hashed_password,
    )


def get_password_hash(password: str):
    return pwd_context.hash(password)


# ============================================================
# USER FUNCTIONS
# ============================================================

def get_user_by_email(
    db: Session,
    email: str,
):
    return (
        db.query(User)
        .filter(User.email == email.lower())
        .first()
    )


def create_user_in_db(
    db: Session,
    name: str,
    email: str,
    password: str,
    role: str = "customer",
):
    user = User(
        name=name,
        email=email.lower(),
        password=get_password_hash(password),
        role=role,
        active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def _session_payload(db: Session, user: User) -> dict:
    """
    The single source of truth for who is signed in.

    The client is never asked what role or id it has - the token is
    built from the row that was just read out of the database.
    """
    token = create_access_token(
        {
            "user_id": user.id,
            "user_name": user.name,
            "email": user.email,
            "role": user.role,
        }
    )

    customer = None

    if user.customer_id:
        customer = (
            db.query(Customer).filter(Customer.id == user.customer_id).first()
        )

    return {
        "message": "Authenticated",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "active": bool(user.active),
            "loyalty_points": user.loyalty_points or 0,
            "customer_id": user.customer_id,
            # The CRM profile the order history is attached to, when
            # the identity backfill has linked one.
            "customer_name": customer.name if customer else None,
        },
        "token": token,
    }


# ============================================================
# CREATE DEFAULT DEMO ACCOUNTS
# ============================================================

def create_default_users(db: Session):
    """
    Creates the default Customer and Admin accounts
    only if they do not already exist.
    """

    customer_email = "customer@gmail.com"
    admin_email = "admin@gmail.com"
    default_password = "password123"

    # ---------------- CUSTOMER ----------------
    customer = get_user_by_email(
        db,
        customer_email,
    )

    if not customer:
        create_user_in_db(
            db=db,
            name="Guest Customer",
            email=customer_email,
            password=default_password,
            role="customer",
        )

    # ---------------- ADMIN ----------------
    admin = get_user_by_email(
        db,
        admin_email,
    )

    if not admin:
        create_user_in_db(
            db=db,
            name="Restaurant Admin",
            email=admin_email,
            password=default_password,
            role="admin",
        )


# ============================================================
# REGISTER CUSTOMER
# ============================================================

@router.post("/register")
def register(
    data: RegisterRequest,
    db: Session = Depends(get_db),
):
    email = data.email.lower().strip()

    existing = get_user_by_email(
        db,
        email,
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )

    # Public registration always creates CUSTOMER accounts.
    # Users cannot create themselves as admins.
    user = create_user_in_db(
        db=db,
        name=data.name,
        email=email,
        password=data.password,
        role="customer",
    )

    return _session_payload(db, user)


# ============================================================
# LOGIN
# ============================================================

@router.post("/login")
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    email = data.email.lower().strip()

    user = get_user_by_email(
        db,
        email,
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not verify_password(
        data.password,
        user.password,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not user.active:
        raise HTTPException(
            status_code=403,
            detail="This account has been deactivated",
        )

    return _session_payload(db, user)


# ============================================================
# CURRENT SESSION
#
# The frontend calls this on load instead of trusting whatever role it
# kept in localStorage.
# ============================================================

@router.get("/me")
def read_current_user(
    current_user=Depends(require_current_user),
):
    return {
        "user": {
            "id": current_user["user_id"],
            "name": current_user["user_name"],
            "email": current_user["email"],
            "role": current_user["role"],
            "active": current_user["active"],
            "loyalty_points": current_user["loyalty_points"],
            "customer_id": current_user["customer_id"],
        }
    }
