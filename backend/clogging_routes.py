"""Bounded, explicit hypothetical drainage-loss scenario endpoints."""
import math
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .clogging import ScenarioStale
from .rainfall_routes import representation


class ScenarioFileResponse(FileResponse):
    """Keep a cloud cache lease until file/range sending ends or is cancelled."""
    def __init__(self,*args,lease,**kwargs):
        super().__init__(*args,**kwargs)
        self.lease=lease

    async def __call__(self,scope,receive,send):
        try:
            await super().__call__(scope,receive,send)
        finally:
            self.lease.__exit__(None,None,None)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    geometry: dict
    selected_route_ids: list[str] | None = Field(default=None, max_length=2000)
    rainfall_mm: float = Field(default=30, ge=0, le=1000)
    duration_minutes: float = Field(default=60, ge=1, le=1440)
    drainage_capacity_mm_h: float = Field(default=15, ge=0, le=500)
    blockage_percent: float = Field(default=100, ge=0, le=100)
    influence_distance_m: float = Field(default=50, ge=5, le=500)
    runoff_coefficient: float = Field(default=.9, ge=0, le=1)
    river_proximity_m: float = Field(default=100, ge=5, le=1000)

    @field_validator('rainfall_mm','duration_minutes','drainage_capacity_mm_h',
                     'blockage_percent','influence_distance_m','runoff_coefficient','river_proximity_m')
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value): raise ValueError('Finite scenario parameters required')
        return value


def create_clogging_router(scenarios, renderer=''):
    router = APIRouter(prefix='/api/clogging',tags=['hypothetical blockage scenario'])

    def call(operation):
        try:
            return operation()
        except ScenarioStale as error:
            raise HTTPException(409,str(error))
        except KeyError as error:
            raise HTTPException(404,str(error))
        except RuntimeError as error:
            raise HTTPException(503,str(error))
        except (OSError, ValueError) as error:
            raise HTTPException(422,str(error))

    @router.get('/meta')
    def meta(request: Request):
        return representation(request,scenarios.meta())

    @router.post('/scenarios')
    def create(request: Request, body: ScenarioRequest):
        result = call(lambda: scenarios.create(**body.model_dump()))
        return representation(request,result)

    @router.get('/scenarios/{scenario_id}')
    def result(request: Request, scenario_id: str):
        return representation(request,call(lambda: scenarios.result(scenario_id)))

    @router.get('/scenarios/{scenario_id}/tiles/{mode}/{z}/{x}/{y}.png')
    def tile(request: Request, scenario_id: str, mode: Literal['baseline','clogged','change','depth_baseline','depth_clogged','depth_change'], z: int, x: int, y: int,
             river_filter: Literal['all','river_adjacent','away','river_adjacent_possible_mixed','away_from_mapped_river']='all'):
        data = call(lambda: scenarios.tile(scenario_id,mode,z,x,y,renderer,river_filter))
        # A source snapshot is checked on every request before immutable serving.
        return representation(request,data,'image/png',immutable=True)

    @router.get('/scenarios/{scenario_id}/download')
    def download(scenario_id: str):
        lease=call(lambda: scenarios.cache_lease(scenario_id))
        call(lease.__enter__)
        try:
            call(lambda: scenarios.result(scenario_id))
            return ScenarioFileResponse(scenarios.path(scenario_id)/'runoff.tif',media_type='image/tiff',
                                        filename='drainage_loss_'+scenario_id+'.tif',lease=lease)
        except BaseException:
            lease.__exit__(None,None,None)
            raise

    return router
