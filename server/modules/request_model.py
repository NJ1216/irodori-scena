from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """HTTP input model that rejects fields unsupported by the running API."""

    model_config = ConfigDict(extra="forbid")
