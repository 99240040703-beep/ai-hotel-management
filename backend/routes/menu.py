import base64
import binascii
import secrets
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
    from models import Menu
    from schemas import ImageUpload, MenuBulkUpdate, MenuCreate
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
    from ..models import Menu
    from ..schemas import ImageUpload, MenuBulkUpdate, MenuCreate


router = APIRouter(
    prefix="/menu",
    tags=["Menu"],
)


# ============================================================
# DISH IMAGE UPLOADS
# Images are written to backend/static/menu and served from
# /static/menu by the app entry point.
# ============================================================

MENU_IMAGE_DIR = (
    Path(__file__).resolve().parent.parent / "static" / "menu"
)

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def get_menu_image_dir() -> Path:
    MENU_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    return MENU_IMAGE_DIR


def store_image(content: bytes, content_type: str) -> dict:
    """Validates and writes one dish image, returning its public URL."""
    normalized_type = (content_type or "").strip().lower()

    if normalized_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG, WEBP or GIF images are allowed",
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty",
        )

    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Image must be smaller than 5 MB",
        )

    file_name = (
        f"{secrets.token_hex(8)}"
        f"{ALLOWED_IMAGE_TYPES[normalized_type]}"
    )

    destination = get_menu_image_dir() / file_name

    with open(destination, "wb") as image_file:
        image_file.write(content)

    return {
        "message": "Image uploaded successfully",
        "file_name": file_name,
        "image_url": f"/static/menu/{file_name}",
    }


# ============================================================
# GET ALL MENU ITEMS
# Public endpoint
# Customers need access to the menu without admin login.
# ============================================================
@router.get("/")
def get_menu(
    category: str | None = None,
    search: str | None = None,
    available_only: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(Menu)

    if category and category.lower() != "all":
        query = query.filter(Menu.category == category)

    if search:
        term = f"%{search.strip().lower()}%"

        query = query.filter(
            or_(
                Menu.name.ilike(term),
                Menu.category.ilike(term),
            )
        )

    if available_only:
        query = query.filter(Menu.available.is_(True))

    # Chef's picks first, then by name for a stable alphabetical order.
    items = query.order_by(Menu.is_featured.desc(), Menu.name.asc()).all()

    return items


# ============================================================
# LIST CATEGORIES
# Public endpoint - drives the category filter pills.
# ============================================================
@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = (
        db.query(Menu.category, Menu.available)
        .all()
    )

    counts = {}

    for category, available in rows:
        if not category:
            continue

        entry = counts.setdefault(
            category, {"category": category, "total": 0, "available": 0}
        )

        entry["total"] += 1

        if available:
            entry["available"] += 1

    return sorted(counts.values(), key=lambda row: row["category"])


# ============================================================
# ADD MENU ITEM
# Admin only
# ============================================================
@router.post("/")
def add_menu(
    item: MenuCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    new_item = Menu(
        name=item.name,
        category=item.category,
        price=item.price,
        available=item.available,
        image_url=item.image_url,
        description=item.description,
        is_vegetarian=item.is_vegetarian,
        is_featured=item.is_featured,
        spice_level=item.spice_level,
        prep_time=item.prep_time,
    )

    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    return new_item


# ============================================================
# UPDATE MENU ITEM
# Admin only
# ============================================================
@router.put("/{item_id}")
def update_menu(
    item_id: int,
    item: MenuCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    menu_item = (
        db.query(Menu)
        .filter(Menu.id == item_id)
        .first()
    )

    if not menu_item:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    menu_item.name = item.name
    menu_item.category = item.category
    menu_item.price = item.price
    menu_item.image_url = item.image_url
    menu_item.available = item.available
    menu_item.description = item.description
    menu_item.is_vegetarian = item.is_vegetarian
    menu_item.is_featured = item.is_featured
    menu_item.spice_level = item.spice_level
    menu_item.prep_time = item.prep_time

    db.commit()
    db.refresh(menu_item)

    return menu_item


# ============================================================
# BULK UPDATE SELECTED MENU ITEMS
# Admin only
# The admin table lets the user tick several dishes and apply one
# action - mark available, feature, re-categorise - at once.
# ============================================================
@router.patch("/bulk")
def bulk_update_menu(
    payload: MenuBulkUpdate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    if not payload.ids:
        raise HTTPException(
            status_code=400,
            detail="No menu items selected",
        )

    items = (
        db.query(Menu)
        .filter(Menu.id.in_(payload.ids))
        .all()
    )

    if not items:
        raise HTTPException(
            status_code=404,
            detail="Menu items not found",
        )

    for menu_item in items:
        if payload.available is not None:
            menu_item.available = payload.available

        if payload.is_featured is not None:
            menu_item.is_featured = payload.is_featured

        if payload.is_vegetarian is not None:
            menu_item.is_vegetarian = payload.is_vegetarian

        if payload.category:
            menu_item.category = payload.category

    db.commit()

    for menu_item in items:
        db.refresh(menu_item)

    return {
        "message": f"Updated {len(items)} menu items",
        "items": items,
    }


# ============================================================
# DELETE SELECTED MENU ITEMS
# Admin only
# ============================================================
@router.delete("/bulk")
def bulk_delete_menu(
    payload: MenuBulkUpdate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    if not payload.ids:
        raise HTTPException(
            status_code=400,
            detail="No menu items selected",
        )

    deleted = (
        db.query(Menu)
        .filter(Menu.id.in_(payload.ids))
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "message": f"Deleted {deleted} menu items",
        "deleted": deleted,
    }


# ============================================================
# UPLOAD DISH IMAGE (BASE64)
# Admin only
#
# This JSON endpoint needs no extra dependency, so image upload
# keeps working even when python-multipart is not installed.
# ============================================================
@router.post("/upload-image")
def upload_menu_image_base64(
    payload: ImageUpload,
    current_admin=Depends(require_admin),
):
    raw_data = payload.data or ""

    # Accepts both a bare base64 string and a full data URL.
    if raw_data.startswith("data:"):
        _, _, raw_data = raw_data.partition(",")

    try:
        content = base64.b64decode(raw_data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Image data is not valid base64",
        )

    content_type = payload.content_type or "image/png"

    if content_type == "image/png" and payload.file_name:
        suffix = Path(payload.file_name).suffix.lower()

        if suffix in ALLOWED_IMAGE_TYPES.values():
            content_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }[suffix]

    return store_image(content, content_type)


# Multipart upload is only registered when python-multipart is
# available, so a missing optional dependency cannot break startup.
try:
    import multipart  # noqa: F401

    MULTIPART_AVAILABLE = True
except ImportError:
    MULTIPART_AVAILABLE = False


if MULTIPART_AVAILABLE:

    @router.post("/upload-image-file")
    async def upload_menu_image(
        file: UploadFile = File(...),
        current_admin=Depends(require_admin),
    ):
        return store_image(await file.read(), file.content_type)

else:  # pragma: no cover - depends on the local environment

    @router.post("/upload-image-file")
    def upload_menu_image_unavailable(
        current_admin=Depends(require_admin),
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Multipart uploads need the python-multipart package. "
                "Install it or use the base64 upload endpoint."
            ),
        )


# ============================================================
# CHANGE MENU AVAILABILITY
# Admin only
# ============================================================
@router.patch("/{item_id}/availability")
def toggle_availability(
    item_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    menu_item = (
        db.query(Menu)
        .filter(Menu.id == item_id)
        .first()
    )

    if not menu_item:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    menu_item.available = not menu_item.available

    db.commit()
    db.refresh(menu_item)

    return menu_item


# ============================================================
# UPDATE PRICE
# Admin only
# Used by Dynamic Pricing
# ============================================================
@router.patch("/{item_id}/price")
def update_price(
    item_id: int,
    price_data: dict,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    menu_item = (
        db.query(Menu)
        .filter(Menu.id == item_id)
        .first()
    )

    if not menu_item:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    new_price = price_data.get("price")

    if new_price is None:
        raise HTTPException(
            status_code=400,
            detail="Price is required",
        )

    try:
        new_price = float(new_price)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Price must be a valid number",
        )

    if new_price < 0:
        raise HTTPException(
            status_code=400,
            detail="Price cannot be negative",
        )

    menu_item.price = new_price

    db.commit()
    db.refresh(menu_item)

    return menu_item


# ============================================================
# UPDATE PRICE BY MENU ITEM NAME
# Admin only
# ============================================================
@router.patch("/by-name/{name}/price")
def update_price_by_name(
    name: str,
    price_data: dict,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    menu_item = (
        db.query(Menu)
        .filter(Menu.name == name)
        .first()
    )

    if not menu_item:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    new_price = price_data.get("price")

    if new_price is None:
        raise HTTPException(
            status_code=400,
            detail="Price is required",
        )

    try:
        new_price = float(new_price)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Price must be a valid number",
        )

    if new_price < 0:
        raise HTTPException(
            status_code=400,
            detail="Price cannot be negative",
        )

    menu_item.price = new_price

    db.commit()
    db.refresh(menu_item)

    return menu_item

# ============================================================
# DELETE MENU ITEM
# Admin only
#
# Declared last on purpose: FastAPI matches routes in declaration
# order, so /{item_id} has to come after every literal path such
# as /bulk or /by-name/{name}/price.
# ============================================================
@router.delete("/{item_id}")
def delete_menu(
    item_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    menu_item = (
        db.query(Menu)
        .filter(Menu.id == item_id)
        .first()
    )

    if not menu_item:
        raise HTTPException(
            status_code=404,
            detail="Menu item not found",
        )

    db.delete(menu_item)
    db.commit()

    return {
        "message": "Menu item deleted successfully",
    }