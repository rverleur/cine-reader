"""Header/setup dataclasses and binary parsing helpers for Phantom CINE files."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, BinaryIO

import numpy as np


def _decode_text(raw: bytes) -> str:
    """Decode NUL-terminated text from setup/header payload bytes."""
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()


def _f32(data: bytes, start: int) -> float:
    return struct.unpack("<f", data[start:start + 4])[0]


def _f64(data: bytes, start: int) -> float:
    return struct.unpack("<d", data[start:start + 8])[0]


@dataclass
class CineHeader:
    """CINE file header (44 bytes at file start)."""

    FileHeaderData: bytes  # Raw 44-byte header block.
    Type: bytes  # File signature (e.g., b"CI").
    Headersize: int  # Header size in bytes.
    Compression: int  # Compression identifier.
    Version: int  # Offset table version (0=32-bit, 1=64-bit).
    FirstMovieImage: int  # First movie image index.
    TotalImageCount: int  # Total images in movie.
    FirstImageNo: int  # Global frame number of first stored image.
    ImageCount: int  # Number of stored images in this cine.
    OffImageHeader: int  # Byte offset to BITMAPINFOHEADER.
    OffSetup: int  # Byte offset to setup block.
    OffImageOffsets: int  # Byte offset to image-offset table.
    TriggerTime: int  # 64-bit trigger timestamp token from header.

    @property
    def first_frame_number(self) -> int:
        """Alias for `FirstImageNo`."""
        return int(self.FirstImageNo)

    @property
    def total_frames(self) -> int:
        """Alias for `ImageCount`."""
        return int(self.ImageCount)

    @property
    def last_frame_number(self) -> int:
        """Derived last frame number (`FirstImageNo + ImageCount - 1`)."""
        return int(self.FirstImageNo) + int(self.ImageCount) - 1


@dataclass
class BitmapHeader:
    """Bitmap (DIB) image header block."""

    ImageHeaderData: bytes  # Raw 40-byte bitmap header payload.
    biSize: int  # DIB header size.
    biWidth: int  # Image width in pixels.
    biHeight: int  # Signed image height (negative means top-down).
    biPlanes: int  # Number of color planes.
    biBitCount: int  # Container bit depth (8/16/24/48 expected).
    biCompression: int  # Compression mode code.
    biSizeImage: int  # Declared image byte count.
    biXPelsPerMeter: int  # Horizontal pixels-per-meter.
    biYPelsPerMeter: int  # Vertical pixels-per-meter.
    biClrUsed: int  # Color table entries in use.
    biClrImportant: int  # Number of important colors.

    @property
    def width(self) -> int:
        """Alias for `biWidth`."""
        return int(self.biWidth)

    @property
    def height(self) -> int:
        """Absolute image height in pixels."""
        return abs(int(self.biHeight))

    @property
    def bit_count(self) -> int:
        """Alias for `biBitCount`."""
        return int(self.biBitCount)


@dataclass
class ImageOffsets:
    """Frame offset table (plus file-size sentinel)."""

    pImageData: bytes  # Raw bytes of offsets table.
    pImage: np.ndarray  # `uint64` offsets array with N+1 entries.

    @property
    def image_offsets(self) -> np.ndarray:
        """Alias for `pImage`."""
        return self.pImage


@dataclass
class Setup:
    """Camera setup block.

    This dataclass keeps frequently used setup values as explicit fields and
    also exposes parsed setup keys as dynamic attributes for compatibility.
    """

    SetupData: bytes  # Raw setup block bytes (`OffSetup .. OffImageOffsets`).
    Length: int = 0  # Setup block length field.
    FrameRate: int = 0  # Integer frame rate from setup block.
    dFrameRate: float = 0.0  # Floating-point frame rate when available.
    Shutter: int = 0  # Legacy shutter/exposure token.
    ShutterNs: int = 0  # Exposure time in nanoseconds.
    RecordingTimeZone: int = 0  # Time-zone offset token from setup block.
    RealBPP: int = 0  # Sensor bit depth (e.g., 10/12/14).
    bEnableColor: bool = False  # Color enable flag.
    Description: str = ""  # User description text.
    LensDescription: str = ""  # Lens description text.
    CineName: str = ""  # Cine clip name.
    CreatedBy: str = ""  # Creator/user text.
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for key, value in self._extra.items():
            setattr(self, key, value)

    @property
    def frame_rate_hz(self) -> float:
        """Best available frame rate in Hz (`dFrameRate` preferred)."""
        if float(self.dFrameRate) > 0.0:
            return float(self.dFrameRate)
        return float(self.FrameRate)

    @property
    def exposure_time_ns(self) -> int:
        """Best available exposure time in nanoseconds."""
        if int(self.ShutterNs) > 0:
            return int(self.ShutterNs)
        return int(self.Shutter)

    @property
    def exposure_time_seconds(self) -> float:
        """Best available exposure time in seconds."""
        ns = self.exposure_time_ns
        return float(ns) * 1e-9 if ns > 0 else 0.0


def read_cine_header(file_obj: BinaryIO) -> CineHeader:
    """Read and parse the fixed-size CINE file header."""
    file_obj.seek(0, 0)
    raw = file_obj.read(44)
    return CineHeader(
        FileHeaderData=raw,
        Type=raw[0:2],
        Headersize=int.from_bytes(raw[2:4], "little", signed=False),
        Compression=int.from_bytes(raw[4:6], "little", signed=False),
        Version=int.from_bytes(raw[6:8], "little", signed=False),
        FirstMovieImage=int.from_bytes(raw[8:12], "little", signed=True),
        TotalImageCount=int.from_bytes(raw[12:16], "little", signed=False),
        FirstImageNo=int.from_bytes(raw[16:20], "little", signed=True),
        ImageCount=int.from_bytes(raw[20:24], "little", signed=False),
        OffImageHeader=int.from_bytes(raw[24:28], "little", signed=False),
        OffSetup=int.from_bytes(raw[28:32], "little", signed=False),
        OffImageOffsets=int.from_bytes(raw[32:36], "little", signed=False),
        TriggerTime=int.from_bytes(raw[36:44], "little", signed=False),
    )


def read_bitmap_header(file_obj: BinaryIO, *, off_image_header: int) -> BitmapHeader:
    """Read and parse the 40-byte BITMAPINFOHEADER block."""
    file_obj.seek(off_image_header, 0)
    raw = file_obj.read(40)
    return BitmapHeader(
        ImageHeaderData=raw,
        biSize=int.from_bytes(raw[0:4], "little", signed=False),
        biWidth=int.from_bytes(raw[4:8], "little", signed=True),
        biHeight=int.from_bytes(raw[8:12], "little", signed=True),
        biPlanes=int.from_bytes(raw[12:14], "little", signed=False),
        biBitCount=int.from_bytes(raw[14:16], "little", signed=False),
        biCompression=int.from_bytes(raw[16:20], "little", signed=False),
        biSizeImage=int.from_bytes(raw[20:24], "little", signed=False),
        biXPelsPerMeter=int.from_bytes(raw[24:28], "little", signed=True),
        biYPelsPerMeter=int.from_bytes(raw[28:32], "little", signed=True),
        biClrUsed=int.from_bytes(raw[32:36], "little", signed=False),
        biClrImportant=int.from_bytes(raw[36:40], "little", signed=False),
    )


def read_image_offsets(
    file_obj: BinaryIO,
    *,
    off_image_offsets: int,
    image_count: int,
    version: int,
) -> ImageOffsets:
    """Read the frame offset table and append file-size sentinel."""
    file_obj.seek(off_image_offsets, 0)
    if version == 0:
        raw = file_obj.read(image_count * 4)
        offsets = np.frombuffer(raw, dtype="<u4").astype(np.uint64, copy=False)
    elif version == 1:
        raw = file_obj.read(image_count * 8)
        offsets = np.frombuffer(raw, dtype="<u8").astype(np.uint64, copy=False)
    else:
        raise ValueError(f"Invalid file version: {version}")

    file_obj.seek(0, 2)
    file_size = np.uint64(file_obj.tell())
    offsets = np.concatenate((offsets, np.array([file_size], dtype=np.uint64)))
    return ImageOffsets(pImageData=raw, pImage=offsets)


def read_setup(
    file_obj: BinaryIO,
    *,
    off_setup: int,
    off_image_offsets: int,
) -> Setup:
    """Read and parse the setup block fields used by the reader."""
    file_obj.seek(off_setup, 0)
    setup_data = file_obj.read(off_image_offsets - off_setup)
    values: dict[str, Any] = {}

    values["FrameRate16"] = int.from_bytes(setup_data[0:2], "little", signed=False)
    values["Shutter16"] = int.from_bytes(setup_data[2:4], "little", signed=False)
    values["PostTrigger16"] = int.from_bytes(setup_data[4:6], "little", signed=False)
    values["FrameDelay16"] = int.from_bytes(setup_data[6:8], "little", signed=False)
    values["AspectRatio"] = int.from_bytes(setup_data[8:10], "little", signed=False)
    values["Res7"] = int.from_bytes(setup_data[10:12], "little", signed=False)
    values["Res8"] = int.from_bytes(setup_data[12:14], "little", signed=False)
    values["Res9"] = int.from_bytes(setup_data[14:15], "little", signed=False)
    values["Res10"] = int.from_bytes(setup_data[15:16], "little", signed=False)
    values["Res11"] = int.from_bytes(setup_data[16:17], "little", signed=False)
    values["TrigFrame"] = int.from_bytes(setup_data[17:18], "little", signed=False)
    values["Res12"] = int.from_bytes(setup_data[18:19], "little", signed=False)
    values["DescriptionOld"] = setup_data[19:140]
    values["Mark"] = setup_data[140:142]
    values["Length"] = int.from_bytes(setup_data[142:144], "little", signed=False)
    values["Res13"] = int.from_bytes(setup_data[144:146], "little", signed=False)
    values["SigOption"] = int.from_bytes(setup_data[146:148], "little", signed=False)
    values["BinChannels"] = int.from_bytes(setup_data[148:150], "little", signed=True)
    values["SamplesPerImage"] = int.from_bytes(setup_data[150:151], "little", signed=False)
    values["BinName"] = [setup_data[151 + 11 * i:162 + 11 * i] for i in range(8)]
    values["AnaOption"] = int.from_bytes(setup_data[239:241], "little", signed=False)
    values["AnaChannels"] = int.from_bytes(setup_data[241:243], "little", signed=True)
    values["Res6"] = int.from_bytes(setup_data[243:244], "little", signed=False)
    values["AnaBoard"] = int.from_bytes(setup_data[244:245], "little", signed=False)
    values["ChOption"] = [
        int.from_bytes(setup_data[245 + 2 * i:247 + 2 * i], "little", signed=False)
        for i in range(8)
    ]
    values["AnaGain"] = [_f32(setup_data, 261 + 4 * i) for i in range(8)]
    values["AnaUnit"] = [setup_data[293 + 6 * i:299 + 6 * i] for i in range(8)]
    values["AnaName"] = [setup_data[341 + 11 * i:352 + 11 * i] for i in range(8)]
    values["lFirstImage"] = int.from_bytes(setup_data[429:433], "little", signed=True)
    values["dwImageCount"] = int.from_bytes(setup_data[433:437], "little", signed=False)
    values["nQFactor"] = int.from_bytes(setup_data[437:439], "little", signed=True)
    values["wCineFileType"] = int.from_bytes(setup_data[439:441], "little", signed=False)
    values["szCinePath"] = [setup_data[441 + 65 * i:506 + 65 * i] for i in range(4)]
    values["Res14"] = int.from_bytes(setup_data[701:703], "little", signed=False)
    values["Res15"] = int.from_bytes(setup_data[703:704], "little", signed=False)
    values["Res16"] = int.from_bytes(setup_data[704:705], "little", signed=False)
    values["Res17"] = int.from_bytes(setup_data[705:707], "little", signed=False)
    values["Res18"] = int.from_bytes(setup_data[707:715], "little", signed=False)
    values["Res19"] = int.from_bytes(setup_data[715:723], "little", signed=False)
    values["Res20"] = int.from_bytes(setup_data[723:725], "little", signed=False)
    values["Res1"] = int.from_bytes(setup_data[725:729], "little", signed=False)
    values["Res2"] = int.from_bytes(setup_data[729:733], "little", signed=False)
    values["Res3"] = int.from_bytes(setup_data[733:737], "little", signed=False)
    values["ImWidth"] = int.from_bytes(setup_data[737:739], "little", signed=False)
    values["ImHeight"] = int.from_bytes(setup_data[739:741], "little", signed=False)
    values["EDRShutter16"] = int.from_bytes(setup_data[741:743], "little", signed=False)
    values["Serial"] = int.from_bytes(setup_data[743:747], "little", signed=False)
    values["Saturation"] = int.from_bytes(setup_data[747:751], "little", signed=True)
    values["Res5"] = int.from_bytes(setup_data[751:752], "little", signed=False)
    values["AutoExposure"] = int.from_bytes(setup_data[752:756], "little", signed=False)
    values["bFlipH"] = bool(int.from_bytes(setup_data[756:760], "little", signed=False))
    values["bFlipV"] = bool(int.from_bytes(setup_data[760:764], "little", signed=False))
    values["Grid"] = int.from_bytes(setup_data[764:768], "little", signed=False)
    values["FrameRate"] = int.from_bytes(setup_data[768:772], "little", signed=False)
    values["Shutter"] = int.from_bytes(setup_data[772:776], "little", signed=False)
    values["EDRSshutter"] = int.from_bytes(setup_data[776:780], "little", signed=False)
    values["PostTrigger"] = int.from_bytes(setup_data[780:784], "little", signed=False)
    values["FrameDelay"] = int.from_bytes(setup_data[784:788], "little", signed=False)
    values["bEnableColor"] = bool(int.from_bytes(setup_data[788:792], "little", signed=False))
    values["CameraVersion"] = int.from_bytes(setup_data[792:796], "little", signed=False)
    values["FirmwareVersion"] = int.from_bytes(setup_data[796:800], "little", signed=False)
    values["SoftwareVersion"] = int.from_bytes(setup_data[800:804], "little", signed=False)
    values["RecordingTimeZone"] = int.from_bytes(setup_data[804:808], "little", signed=True)
    values["CFA"] = int.from_bytes(setup_data[808:812], "little", signed=False)
    values["Bright"] = int.from_bytes(setup_data[812:816], "little", signed=True)
    values["Contrast"] = int.from_bytes(setup_data[816:820], "little", signed=True)
    values["Gamma"] = int.from_bytes(setup_data[820:824], "little", signed=True)
    values["Res21"] = int.from_bytes(setup_data[824:828], "little", signed=False)
    values["AutoExpLevel"] = int.from_bytes(setup_data[828:832], "little", signed=False)
    values["AutoExpSpeed"] = int.from_bytes(setup_data[832:836], "little", signed=False)
    values["AutoExpRect"] = [
        [
            int.from_bytes(setup_data[836 + 4 * a + 8 * b:840 + 4 * a + 8 * b], "little", signed=False)
            for a in range(2)
        ]
        for b in range(2)
    ]
    values["WBGain"] = [[_f32(setup_data, 852 + 4 * b + 8 * a) for b in range(2)] for a in range(4)]
    values["Rotate"] = int.from_bytes(setup_data[884:888], "little", signed=True)
    values["WBView"] = [_f32(setup_data, 888 + 4 * b) for b in range(2)]
    values["RealBPP"] = int.from_bytes(setup_data[896:900], "little", signed=False)
    values["Conv8Min"] = int.from_bytes(setup_data[900:904], "little", signed=False)
    values["Conv8Max"] = int.from_bytes(setup_data[904:908], "little", signed=False)
    values["FilterCode"] = int.from_bytes(setup_data[908:912], "little", signed=True)
    values["FilterParam"] = int.from_bytes(setup_data[912:916], "little", signed=True)
    values["UF"] = [
        int.from_bytes(setup_data[916:920], "little", signed=True),
        int.from_bytes(setup_data[920:924], "little", signed=True),
        int.from_bytes(setup_data[924:928], "little", signed=True),
        [int.from_bytes(setup_data[928 + 4 * a:932 + 4 * a], "little", signed=True) for a in range(25)],
    ]
    values["BlackCalSVer"] = int.from_bytes(setup_data[1028:1032], "little", signed=False)
    values["WhiteCalSVer"] = int.from_bytes(setup_data[1032:1036], "little", signed=False)
    values["GrayCalSVer"] = int.from_bytes(setup_data[1036:1040], "little", signed=False)
    values["bStampTime"] = bool(int.from_bytes(setup_data[1040:1044], "little", signed=False))
    values["SoundDest"] = int.from_bytes(setup_data[1044:1048], "little", signed=False)
    values["FRPSteps"] = int.from_bytes(setup_data[1048:1052], "little", signed=False)
    values["FRPImgNr"] = [int.from_bytes(setup_data[1052 + 4 * a:1056 + 4 * a], "little", signed=True) for a in range(16)]
    values["FRPRate"] = [int.from_bytes(setup_data[1116 + 4 * a:1120 + 4 * a], "little", signed=False) for a in range(16)]
    values["FRPExp"] = [int.from_bytes(setup_data[1180 + 4 * a:1184 + 4 * a], "little", signed=False) for a in range(16)]
    values["MCCnt"] = int.from_bytes(setup_data[1244:1248], "little", signed=True)
    values["MCPercent"] = [_f32(setup_data, 1248 + 4 * a) for a in range(64)]
    values["CICalib"] = int.from_bytes(setup_data[1504:1508], "little", signed=False)
    values["CalibWidth"] = int.from_bytes(setup_data[1508:1512], "little", signed=False)
    values["CalibHeight"] = int.from_bytes(setup_data[1512:1516], "little", signed=False)
    values["CalibRate"] = int.from_bytes(setup_data[1516:1520], "little", signed=False)
    values["CalibExp"] = int.from_bytes(setup_data[1520:1524], "little", signed=False)
    values["CalibEDR"] = int.from_bytes(setup_data[1524:1528], "little", signed=False)
    values["CalibTemp"] = int.from_bytes(setup_data[1528:1532], "little", signed=False)
    values["HeadSerial"] = [int.from_bytes(setup_data[1532 + 4 * a:1536 + 4 * a], "little", signed=False) for a in range(4)]
    values["RangeCode"] = int.from_bytes(setup_data[1548:1552], "little", signed=False)
    values["RangeSize"] = int.from_bytes(setup_data[1552:1556], "little", signed=False)
    values["Decimation"] = int.from_bytes(setup_data[1556:1560], "little", signed=False)
    values["MasterSerial"] = int.from_bytes(setup_data[1560:1564], "little", signed=False)
    values["Sensor"] = int.from_bytes(setup_data[1564:1568], "little", signed=False)
    values["ShutterNs"] = int.from_bytes(setup_data[1568:1572], "little", signed=False)
    values["EDRShutterNs"] = int.from_bytes(setup_data[1572:1576], "little", signed=False)
    values["FrameDelayNs"] = int.from_bytes(setup_data[1576:1580], "little", signed=False)
    values["ImPosXAcq"] = int.from_bytes(setup_data[1580:1584], "little", signed=False)
    values["ImPosYAcq"] = int.from_bytes(setup_data[1584:1588], "little", signed=False)
    values["ImWidthAcq"] = int.from_bytes(setup_data[1588:1592], "little", signed=False)
    values["ImHeightAcq"] = int.from_bytes(setup_data[1592:1596], "little", signed=False)
    values["Description"] = _decode_text(setup_data[1596:5692])
    values["RisingEdge"] = bool(int.from_bytes(setup_data[5692:5696], "little", signed=False))
    values["FilterTime"] = int.from_bytes(setup_data[5696:5700], "little", signed=False)
    values["LongReady"] = bool(int.from_bytes(setup_data[5700:5704], "little", signed=False))
    values["ShutterOff"] = bool(int.from_bytes(setup_data[5704:5708], "little", signed=False))
    values["Res4"] = [int.from_bytes(setup_data[5708 + a:5709 + a], "little", signed=False) for a in range(16)]
    values["bMetaWB"] = bool(int.from_bytes(setup_data[5724:5728], "little", signed=False))
    values["Hue"] = int.from_bytes(setup_data[5728:5732], "little", signed=True)
    values["BlackLevel"] = int.from_bytes(setup_data[5732:5736], "little", signed=True)
    values["WhiteLevel"] = int.from_bytes(setup_data[5736:5740], "little", signed=True)
    values["LensDescription"] = _decode_text(setup_data[5740:5996])
    values["LensAperture"] = _f32(setup_data, 5996)
    values["LensFocusDistance"] = _f32(setup_data, 6000)
    values["LensFocalLength"] = _f32(setup_data, 6004)
    values["fOffset"] = _f32(setup_data, 6008)
    values["fGain"] = _f32(setup_data, 6012)
    values["fSaturation"] = _f32(setup_data, 6016)
    values["fHue"] = _f32(setup_data, 6020)
    values["fGamma"] = _f32(setup_data, 6024)
    values["fGammaR"] = _f32(setup_data, 6028)
    values["fGammaB"] = _f32(setup_data, 6032)
    values["fFlare"] = _f32(setup_data, 6036)
    values["fPedestalR"] = _f32(setup_data, 6040)
    values["fPedestalG"] = _f32(setup_data, 6044)
    values["fPedestalB"] = _f32(setup_data, 6048)
    values["fChroma"] = _f32(setup_data, 6052)
    values["ToneLabel"] = _decode_text(setup_data[6056:6312])
    values["TonePoints"] = int.from_bytes(setup_data[6312:6316], "little", signed=True)
    values["fTone"] = [[_f32(setup_data, 6316 + 4 * b + 8 * a) for b in range(2)] for a in range(32)]
    values["UserMatrixLabel"] = _decode_text(setup_data[6572:6828])
    values["EnableMatrices"] = bool(int.from_bytes(setup_data[6828:6832], "little", signed=False))
    values["cmUser"] = [_f32(setup_data, 6832 + 4 * b) for b in range(9)]
    values["EnableCrop"] = bool(int.from_bytes(setup_data[6868:6872], "little", signed=False))
    values["CropRect"] = [
        [
            int.from_bytes(setup_data[6872 + 4 * a + 8 * b:6876 + 4 * a + 8 * b], "little", signed=False)
            for a in range(2)
        ]
        for b in range(2)
    ]
    values["EnableResample"] = bool(int.from_bytes(setup_data[6888:6892], "little", signed=False))
    values["ResampleWidth"] = int.from_bytes(setup_data[6892:6896], "little", signed=False)
    values["ResampleHeight"] = int.from_bytes(setup_data[6896:6900], "little", signed=False)
    values["fGain16"] = _f32(setup_data, 6900)
    values["FRPShape"] = [int.from_bytes(setup_data[6904 + 4 * a:6908 + 4 * a], "little", signed=False) for a in range(16)]
    values["TrigTC"] = int.from_bytes(setup_data[6968:6976], "little", signed=False)
    values["fPbRate"] = _f32(setup_data, 6976)
    values["fTcRate"] = _f32(setup_data, 6980)
    values["CineName"] = _decode_text(setup_data[6984:7240])
    values["fGainR"] = _f32(setup_data, 7240)
    values["fGainG"] = _f32(setup_data, 7244)
    values["fGainB"] = _f32(setup_data, 7248)
    values["cmCalib"] = [_f32(setup_data, 7252 + 4 * a) for a in range(9)]
    values["fWBTemp"] = _f32(setup_data, 7288)
    values["fWBCc"] = _f32(setup_data, 7292)
    values["CalibrationInfo"] = _decode_text(setup_data[7296:8320])
    values["OpticalFilter"] = _decode_text(setup_data[8320:9344])
    values["GpsInfo"] = _decode_text(setup_data[9344:9600])
    values["Uuid"] = _decode_text(setup_data[9600:9856])
    values["CreatedBy"] = _decode_text(setup_data[9856:10112])
    values["RecBPP"] = int.from_bytes(setup_data[10112:10116], "little", signed=False)
    values["LowestFormatBPP"] = int.from_bytes(setup_data[10116:10118], "little", signed=False)
    values["LowestFormatQ"] = int.from_bytes(setup_data[10118:10120], "little", signed=False)
    values["fToe"] = _f32(setup_data, 10120)
    values["LogMode"] = int.from_bytes(setup_data[10124:10128], "little", signed=False)
    values["CameraModel"] = setup_data[10128:10384]
    values["WBType"] = int.from_bytes(setup_data[10384:10388], "little", signed=False)
    values["fDecimation"] = _f32(setup_data, 10388)
    values["MagSerial"] = int.from_bytes(setup_data[10392:10396], "little", signed=False)
    values["CSSerial"] = int.from_bytes(setup_data[10396:10400], "little", signed=False)
    values["dFrameRate"] = _f64(setup_data, 10400)
    values["SensorMode"] = int.from_bytes(setup_data[10408:10412], "little", signed=False)
    values["UndecFirst"] = int.from_bytes(setup_data[10412:10416], "little", signed=False)
    values["SupportsBinning"] = bool(int.from_bytes(setup_data[10416:10420], "little", signed=False))
    values["UvSensor"] = bool(int.from_bytes(setup_data[10420:10424], "little", signed=False))
    values["AnaDaqDescription"] = setup_data[10424:10552]
    values["BinDaqDescription"] = setup_data[10552:10680]
    values["DaqOptions"] = bool(int.from_bytes(setup_data[10680:10684], "little", signed=False))

    # Legacy typo aliases kept only as secondary names.
    values["LensAperature"] = values["LensAperture"]
    values["EnableMatricies"] = values["EnableMatrices"]

    return Setup(
        SetupData=setup_data,
        Length=int(values.get("Length", 0)),
        FrameRate=int(values.get("FrameRate", 0)),
        dFrameRate=float(values.get("dFrameRate", 0.0)),
        Shutter=int(values.get("Shutter", 0)),
        ShutterNs=int(values.get("ShutterNs", 0)),
        RecordingTimeZone=int(values.get("RecordingTimeZone", 0)),
        RealBPP=int(values.get("RealBPP", 0)),
        bEnableColor=bool(values.get("bEnableColor", False)),
        Description=str(values.get("Description", "")),
        LensDescription=str(values.get("LensDescription", "")),
        CineName=str(values.get("CineName", "")),
        CreatedBy=str(values.get("CreatedBy", "")),
        _extra=values,
    )
