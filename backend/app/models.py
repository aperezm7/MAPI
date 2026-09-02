from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

IucnCode = Literal["EX", "EW", "CR", "EN", "VU", "NT", "LC", "DD", "NE"]
PlaceKind = Literal["country", "bbox", "gadm"]
MapMode = Literal["tiles_plus_sample", "points", "tiles"]
MapStyle = Literal["points", "hex", "heat"]


class TaxonQuery(BaseModel):
    q: str | None = None
    rankHint: str | None = None
    gbifKey: int | None = None
    scientificName: str | None = None
    canonicalName: str | None = None
    rank: str | None = None


class PlaceQuery(BaseModel):
    q: str | None = None
    kind: PlaceKind = "country"
    iso2: str | None = None
    title: str | None = None
    bbox: list[float] | None = None

    @field_validator("iso2")
    @classmethod
    def normalize_iso2(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("bbox must be [minLon, minLat, maxLon, maxLat]")
        return value


class TimeQuery(BaseModel):
    yearMin: int | None = Field(default=None, ge=1000, le=2100)
    yearMax: int | None = Field(default=None, ge=1000, le=2100)


class ConservationQuery(BaseModel):
    iucn: list[IucnCode] = Field(default_factory=list)


class FiltersQuery(BaseModel):
    hasCoordinate: bool = True
    occurrenceStatus: str = "PRESENT"
    basisOfRecord: list[str] | None = None


class MapOptions(BaseModel):
    mode: MapMode = "tiles_plus_sample"
    sampleLimit: int = Field(default=300, ge=1, le=10000)
    style: MapStyle = "points"
    includeInat: bool = False


class MapQuery(BaseModel):
    taxon: TaxonQuery | None = None
    place: PlaceQuery | None = None
    time: TimeQuery | None = None
    conservation: ConservationQuery | None = None
    filters: FiltersQuery = Field(default_factory=FiltersQuery)
    map: MapOptions = Field(default_factory=MapOptions)


class TaxonCandidate(BaseModel):
    gbifKey: int
    scientificName: str | None = None
    canonicalName: str | None = None
    rank: str | None = None
    status: str | None = None
    confidence: int | None = None
    matchType: str | None = None
    kingdom: str | None = None
    className: str | None = Field(default=None, alias="class")
    model_config = {"populate_by_name": True}


class PlaceCandidate(BaseModel):
    iso2: str
    iso3: str | None = None
    title: str
    gbifRegion: str | None = None


class ResolveResponse(BaseModel):
    query: MapQuery
    taxonCandidates: list[TaxonCandidate] = Field(default_factory=list)
    placeCandidates: list[PlaceCandidate] = Field(default_factory=list)
    taxonNeedsDisambiguation: bool = False
    placeNeedsDisambiguation: bool = False
    warnings: list[str] = Field(default_factory=list)


class TileSpec(BaseModel):
    urlTemplate: str
    tileSize: int = 512
    source: Literal["density", "adhoc"] = "density"
    attribution: str = "© GBIF"


class YearCount(BaseModel):
    year: int
    count: int


class MapResponse(BaseModel):
    query: MapQuery
    count: int
    countIsApproximate: bool = False
    tile: TileSpec | None = None
    sample: dict[str, Any]
    sampleTruncated: bool = False
    sampleOmittedSensitive: int = 0
    histogram: list[YearCount] = Field(default_factory=list)
    attribution: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    mode: MapMode = "tiles_plus_sample"
    style: MapStyle = "points"


class NlPlanRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class NlPlanResponse(BaseModel):
    query: MapQuery
    resolve: ResolveResponse
    notes: list[str] = Field(default_factory=list)
    model: str | None = None


class IucnStatusResponse(BaseModel):
    available: bool
    taxonName: str | None = None
    category: str | None = None
    categoryLabel: str | None = None
    assessmentId: int | None = None
    citation: str | None = None
    url: str | None = None
    message: str | None = None
    raw: dict[str, Any] | None = None


class DownloadRequest(BaseModel):
    query: MapQuery
    format: Literal["SIMPLE_CSV", "DWCA"] = "SIMPLE_CSV"


class DownloadResponse(BaseModel):
    available: bool
    key: str | None = None
    statusUrl: str | None = None
    message: str | None = None
