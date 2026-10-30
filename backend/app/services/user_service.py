"""User resolution — giai đoạn này dùng demo user theo header X-User-Id.

Auth đầy đủ (JWT/OAuth) sẽ thay thế ở slice sau. Service giữ nguyên interface
nên việc thay runtime auth không ảnh hưởng callers.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

DEMO_PREFIX = "demo:"


async def get_or_create_user(db: AsyncSession, external_id: str) -> User:
    if not external_id or not external_id.strip():
        external_id = "anonymous"
    external_id = external_id.strip()[:128]

    result = await db.execute(select(User).where(User.external_id == external_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(external_id=external_id, display_name=external_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user
