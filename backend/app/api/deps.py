"""FastAPI dependencies: handlers ask for the Runtime instead of importing globals."""
from typing import Annotated

from fastapi import Depends, Request

from app.runtime import Runtime


def get_rt(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


Rt = Annotated[Runtime, Depends(get_rt)]
