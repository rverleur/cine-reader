"""Reader for Vision Research Phantom `.cine` files."""

from __future__ import annotations

import array
import struct
from pathlib import Path

import numpy as np

from .unpack import unpack_10bit_data


class Cine:
    """High-level reader for Phantom `.cine` files."""

    def __init__(self, filename: str | Path, keep_annotations: bool = True):
        self.filename = str(filename)
        self.keep_annotations = bool(keep_annotations)
        self.file = None
        self.OpenCineFile(self.filename)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.CloseFile()
        return False

    def __del__(self):
        try:
            self.CloseFile()
        except Exception:
            pass

    def OpenCineFile(self, filename):
        """Open a cine file and parse all headers."""
        self.filename = str(filename)
        self.CloseFile()
        self.file = open(filename, mode='rb')
        self.FileHeader = self.CineHeader(self)
        self.ImageHeader = self.BitmapHeader(self)
        self.CameraSetup = self.Setup(self)
        self.ImageLocations = self.ImageOffsets(self)
        self.CurrentFrame = self.FileHeader.FirstImageNo
        self.LoadFrame(self.CurrentFrame)

    def NextFrame(self, increment=1):
        """Load the next frame (or offset by `increment`)."""
        self.CurrentFrame += increment
        self.LoadFrame(self.CurrentFrame)

    def _decode_frame(self, raw: bytes) -> np.ndarray:
        bit_count = int(self.ImageHeader.biBitCount)
        width = int(self.ImageHeader.biWidth)
        height = abs(int(self.ImageHeader.biHeight))
        channels = 1 if bit_count in (8, 16) else 3

        if bit_count in (8, 24):
            row_bytes = width * channels
            row_stride = ((row_bytes + 3) // 4) * 4
            buffer_u8 = np.frombuffer(raw, dtype=np.uint8)
            if buffer_u8.size == height * row_stride:
                rows = buffer_u8.reshape(height, row_stride)[:, :row_bytes]
            elif buffer_u8.size == height * row_bytes:
                rows = buffer_u8.reshape(height, row_bytes)
            else:
                raise ValueError(
                    f"8/24-bit size mismatch: got {buffer_u8.size}, expected "
                    f"{height * row_bytes} or {height * row_stride}"
                )
            if channels == 1:
                return rows.reshape(height, width).copy()
            return rows.reshape(height, width, channels).copy()

        if bit_count not in (16, 48):
            raise ValueError(f"Unsupported bit depth: {bit_count}")

        if int(self.CameraSetup.RealBPP) == 10:
            unpacked = self.unpack_10bit_data(raw)
            expected = height * width * channels
            if unpacked.size < expected:
                raise ValueError(
                    f"Packed 10-bit decode returned {unpacked.size} samples, expected at least {expected}"
                )
            unpacked = unpacked[:expected]
            if channels == 1:
                return unpacked.reshape(height, width)
            return unpacked.reshape(height, width, channels)

        row_bytes = width * channels * 2
        row_stride = ((row_bytes + 3) // 4) * 4
        buffer_u8 = np.frombuffer(raw, dtype=np.uint8)
        if buffer_u8.size == height * row_stride:
            rows_u8 = buffer_u8.reshape(height, row_stride)[:, :row_bytes]
        elif buffer_u8.size == height * row_bytes:
            rows_u8 = buffer_u8.reshape(height, row_bytes)
        else:
            raise ValueError(
                f"16/48-bit size mismatch: got {buffer_u8.size}, expected "
                f"{height * row_bytes} or {height * row_stride}"
            )
        rows_u8 = np.ascontiguousarray(rows_u8)
        values = rows_u8.view("<u2")
        if channels == 1:
            return values.reshape(height, width)
        return values.reshape(height, width, channels)

    def LoadFrame(self, ImageNo, convert_bgr_to_rgb=False):
        """Load a single frame into `self.PixelArray`."""
        first = int(self.FileHeader.FirstImageNo)
        count = int(self.FileHeader.ImageCount)
        index = int(ImageNo) - first
        if index < 0 or index >= count:
            raise IndexError("ImageNo is out of bounds")

        self.CurrentFrame = int(ImageNo)
        start = int(self.ImageLocations.pImage[index])
        stop = int(self.ImageLocations.pImage[index + 1])

        self.file.seek(start, 0)
        self.AnnotationSize = int.from_bytes(self.file.read(4), "little", signed=False)
        self.file.seek(start, 0)
        annotation = self.file.read(self.AnnotationSize)
        if len(annotation) != self.AnnotationSize:
            raise EOFError("Unexpected EOF while reading annotation block")

        if self.keep_annotations:
            self.AnnotationData = annotation
            self.Annotation = self.AnnotationData[4:self.AnnotationSize - 4]
        else:
            self.AnnotationData = b""
            self.Annotation = b""

        if self.AnnotationSize >= 4:
            self.ImageSize = int.from_bytes(annotation[self.AnnotationSize - 4:self.AnnotationSize], "little", signed=False)
        else:
            self.ImageSize = 0

        frame_size_from_offsets = max(0, stop - start - self.AnnotationSize)
        if frame_size_from_offsets and (self.ImageSize == 0 or self.ImageSize > frame_size_from_offsets):
            self.ImageSize = frame_size_from_offsets

        self.ImageData = self.file.read(self.ImageSize)
        if len(self.ImageData) != self.ImageSize:
            raise EOFError("Unexpected EOF while reading frame payload")

        self.PixelArray = self._decode_frame(self.ImageData)
        self.PixelData = self.PixelArray.reshape(-1)

        if convert_bgr_to_rgb and self.PixelArray.ndim == 3:
            self.PixelArray = self.PixelArray[..., ::-1].copy()
            self.PixelData = self.PixelArray.reshape(-1)

    def ReplaceDeadPixels(self, dead_value=4095):
        """Replace dead pixels with the mean of valid 8-neighbors (mono frames)."""
        if self.PixelArray.ndim != 2:
            return

        frame = self.PixelArray
        frame_f = frame.astype(np.float32, copy=False)
        dead_mask = frame == dead_value
        if not np.any(dead_mask):
            return

        valid = ~dead_mask
        values = np.where(valid, frame_f, 0.0)
        valid_i = valid.astype(np.int16)

        pv = np.pad(values, ((1, 1), (1, 1)), mode="constant", constant_values=0.0)
        pm = np.pad(valid_i, ((1, 1), (1, 1)), mode="constant", constant_values=0)

        nbr_sum = (
            pv[:-2, :-2] + pv[:-2, 1:-1] + pv[:-2, 2:] +
            pv[1:-1, :-2] +                 pv[1:-1, 2:] +
            pv[2:, :-2] + pv[2:, 1:-1] + pv[2:, 2:]
        )
        nbr_cnt = (
            pm[:-2, :-2] + pm[:-2, 1:-1] + pm[:-2, 2:] +
            pm[1:-1, :-2] +                 pm[1:-1, 2:] +
            pm[2:, :-2] + pm[2:, 1:-1] + pm[2:, 2:]
        )

        out = frame_f.copy()
        replace_mask = dead_mask & (nbr_cnt > 0)
        out[replace_mask] = nbr_sum[replace_mask] / nbr_cnt[replace_mask]
        self.PixelArray = out.astype(frame.dtype, copy=False)
        self.PixelData = self.PixelArray.reshape(-1)

    def unpack_10bit_data(self, data):
        """Unpack Phantom packed 10-bit payload to `uint16`."""
        return unpack_10bit_data(data)

    def CloseFile(self):
        """Close the current cine file handle."""
        if self.file is not None and not self.file.closed:
            self.file.close()
        self.file = None

    class CineHeader(object):
        """
        Represents the header information of a cine file.

        Reads in the first 44 bytes of the file header and interprets various parameters.
        """

        def __init__(self, Cine):
            """
            Initialize the CineHeader by reading header data from the file.

            Parameters:
                Cine (Cine): The Cine object containing the open file.
            """
            self.FileHeaderData = Cine.file.read(44)
            self.Type = self.FileHeaderData[0:2]
            self.Headersize = int.from_bytes(self.FileHeaderData[2:4], "little", signed=False)  # 16-bit header size
            self.Compression = int.from_bytes(self.FileHeaderData[4:6], "little", signed=False)
            self.Version = int.from_bytes(self.FileHeaderData[6:8], "little", signed=False)
            self.FirstMovieImage = int.from_bytes(self.FileHeaderData[8:12], "little", signed=True)
            self.TotalImageCount = int.from_bytes(self.FileHeaderData[12:16], "little", signed=False)
            self.FirstImageNo = int.from_bytes(self.FileHeaderData[16:20], "little", signed=True)
            self.ImageCount = int.from_bytes(self.FileHeaderData[20:24], "little", signed=False)
            self.OffImageHeader = int.from_bytes(self.FileHeaderData[24:28], "little", signed=False)
            self.OffSetup = int.from_bytes(self.FileHeaderData[28:32], "little", signed=False)
            self.OffImageOffsets = int.from_bytes(self.FileHeaderData[32:36], "little", signed=False)
            self.TriggerTime = int.from_bytes(self.FileHeaderData[36:44], "little", signed=False)

    class BitmapHeader(object):
        """
        Represents the bitmap (image) header from the cine file.

        Reads in 40 bytes from the file starting at the offset given by the file header.
        """

        def __init__(self, Cine):
            """
            Initialize the BitmapHeader by reading image header data.

            Parameters:
                Cine (Cine): The Cine object containing the open file.
            """
            Cine.file.seek(Cine.FileHeader.OffImageHeader, 0)  # Seek to start of bitmap info header
            self.ImageHeaderData = Cine.file.read(40)
            self.biSize = int.from_bytes(self.ImageHeaderData[0:4], "little", signed=False)
            self.biWidth = int.from_bytes(self.ImageHeaderData[4:8], "little", signed=True)
            self.biHeight = int.from_bytes(self.ImageHeaderData[8:12], "little", signed=True)
            self.biPlanes = int.from_bytes(self.ImageHeaderData[12:14], "little", signed=False)
            self.biBitCount = int.from_bytes(self.ImageHeaderData[14:16], "little", signed=False)
            self.biCompression = int.from_bytes(self.ImageHeaderData[16:20], "little", signed=False)
            self.biSizeImage = int.from_bytes(self.ImageHeaderData[20:24], "little", signed=False)
            self.biXPelsPerMeter = int.from_bytes(self.ImageHeaderData[24:28], "little", signed=True)
            self.biYPelsPerMeter = int.from_bytes(self.ImageHeaderData[28:32], "little", signed=True)
            self.biClrUsed = int.from_bytes(self.ImageHeaderData[32:36], "little", signed=False)
            self.biClrImportant = int.from_bytes(self.ImageHeaderData[36:40], "little", signed=False)

    class ImageOffsets(object):
        """
        Represents the offsets for each image frame in the cine file.

        Reads the image offset table and stores offsets in an array.
        """

        def __init__(self, Cine):
            """
            Initialize ImageOffsets by reading offset data from the cine file.

            Parameters:
                Cine (Cine): The Cine object containing the open file.

            Raises:
                Exception: If the file version is invalid.
            """
            Cine.file.seek(Cine.FileHeader.OffImageOffsets, 0)
            if Cine.FileHeader.Version == 0:
                self.pImageData = Cine.file.read(Cine.FileHeader.ImageCount * 4)
                self.pImage = np.frombuffer(self.pImageData, dtype="<u4").astype(np.uint64, copy=False)
            elif Cine.FileHeader.Version == 1:
                self.pImageData = Cine.file.read(Cine.FileHeader.ImageCount * 8)
                self.pImage = np.frombuffer(self.pImageData, dtype="<u8").astype(np.uint64, copy=False)
            else:
                raise Exception("File Version is Invalid")
            Cine.file.seek(0, 2)
            file_size = np.uint64(Cine.file.tell())
            self.pImage = np.concatenate((self.pImage, np.array([file_size], dtype=np.uint64)))

    class Setup(object):
        """
        Represents the camera setup information contained in the cine file.

        Reads the setup data block and parses various camera parameters and metadata.
        """

        def __init__(self, Cine):
            """
            Initialize the Setup by reading and parsing setup data from the file.

            Parameters:
                Cine (Cine): The Cine object containing the open file.
            """
            Cine.file.seek(Cine.FileHeader.OffSetup + 22 + 120, 0)  # Seek to location of length parameter in setup file
            self.Length = int.from_bytes(Cine.file.read(2), "little", signed=False)
            Cine.file.seek(Cine.FileHeader.OffSetup, 0)
            self.SetupData = Cine.file.read(Cine.FileHeader.OffImageOffsets - Cine.FileHeader.OffSetup)
            decode_text = lambda b: b.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
            self.FrameRate16 = int.from_bytes(self.SetupData[0:2], "little", signed=False)
            self.Shutter16 = int.from_bytes(self.SetupData[2:4], "little", signed=False)
            self.PostTrigger16 = int.from_bytes(self.SetupData[4:6], "little", signed=False)
            self.FrameDelay16 = int.from_bytes(self.SetupData[6:8], "little", signed=False)
            self.AspectRatio = int.from_bytes(self.SetupData[8:10], "little", signed=False)
            self.Res7 = int.from_bytes(self.SetupData[10:12], "little", signed=False)
            self.Res8 = int.from_bytes(self.SetupData[12:14], "little", signed=False)
            self.Res9 = int.from_bytes(self.SetupData[14:15], "little", signed=False)
            self.Res10 = int.from_bytes(self.SetupData[15:16], "little", signed=False)
            self.Res11 = int.from_bytes(self.SetupData[16:17], "little", signed=False)
            self.TrigFrame = int.from_bytes(self.SetupData[17:18], "little", signed=False)
            self.Res12 = int.from_bytes(self.SetupData[18:19], "little", signed=False)
            self.DescriptionOld = self.SetupData[19:140]
            self.Mark = self.SetupData[140:142]
            self.Length = int.from_bytes(self.SetupData[142:144], "little", signed=False)
            self.Res13 = int.from_bytes(self.SetupData[144:146], "little", signed=False)
            self.SigOption = int.from_bytes(self.SetupData[146:148], "little", signed=False)
            self.BinChannels = int.from_bytes(self.SetupData[148:150], "little", signed=True)
            self.SamplesPerImage = int.from_bytes(self.SetupData[150:151], "little", signed=False)
            self.BinName = [self.SetupData[151 + 11 * a:162 + 11 * a] for a in range(8)]
            self.AnaOption = int.from_bytes(self.SetupData[239:241], "little", signed=False)
            self.AnaChannels = int.from_bytes(self.SetupData[241:243], "little", signed=True)
            self.Res6 = int.from_bytes(self.SetupData[243:244], "little", signed=False)
            self.AnaBoard = int.from_bytes(self.SetupData[244:245], "little", signed=False)
            self.ChOption = [int.from_bytes(self.SetupData[245 + 2 * a:247 + 2 * a], "little", signed=False) for a in
                             range(8)]
            self.AnaGain = [struct.unpack('f', self.SetupData[261 + 4 * a:265 + 4 * a])[0] for a in range(8)]
            self.AnaUnit = [self.SetupData[293 + 6 * a:299 + 6 * a] for a in range(8)]
            self.AnaName = [self.SetupData[341 + 11 * a:352 + 11 * a] for a in range(8)]
            self.lFirstImage = int.from_bytes(self.SetupData[429:433], "little", signed=True)
            self.dwImageCount = int.from_bytes(self.SetupData[433:437], "little", signed=False)
            self.nQFactor = int.from_bytes(self.SetupData[437:439], "little", signed=True)
            self.wCineFileType = int.from_bytes(self.SetupData[439:441], "little", signed=False)
            self.szCinePath = [self.SetupData[441 + 65 * a:506 + 65 * a] for a in range(4)]
            self.Res14 = int.from_bytes(self.SetupData[701:703], "little", signed=False)
            self.Res15 = int.from_bytes(self.SetupData[703:704], "little", signed=False)
            self.Res16 = int.from_bytes(self.SetupData[704:705], "little", signed=False)
            self.Res17 = int.from_bytes(self.SetupData[705:707], "little", signed=False)
            self.Res18 = int.from_bytes(self.SetupData[707:715], "little", signed=False)
            self.Res19 = int.from_bytes(self.SetupData[715:723], "little", signed=False)
            self.Res20 = int.from_bytes(self.SetupData[723:725], "little", signed=False)
            self.Res1 = int.from_bytes(self.SetupData[725:729], "little", signed=False)
            self.Res2 = int.from_bytes(self.SetupData[729:733], "little", signed=False)
            self.Res3 = int.from_bytes(self.SetupData[733:737], "little", signed=False)
            self.ImWidth = int.from_bytes(self.SetupData[737:739], "little", signed=False)
            self.ImHeight = int.from_bytes(self.SetupData[739:741], "little", signed=False)
            self.EDRShutter16 = int.from_bytes(self.SetupData[741:743], "little", signed=False)
            self.Serial = int.from_bytes(self.SetupData[743:747], "little", signed=False)
            self.Saturation = int.from_bytes(self.SetupData[747:751], "little", signed=True)
            self.Res5 = int.from_bytes(self.SetupData[751:752], "little", signed=False)
            self.AutoExposure = int.from_bytes(self.SetupData[752:756], "little", signed=False)
            self.bFlipH = bool(int.from_bytes(self.SetupData[756:760], "little", signed=False))
            self.bFlipV = bool(int.from_bytes(self.SetupData[760:764], "little", signed=False))
            self.Grid = int.from_bytes(self.SetupData[764:768], "little", signed=False)
            self.FrameRate = int.from_bytes(self.SetupData[768:772], "little", signed=False)
            self.Shutter = int.from_bytes(self.SetupData[772:776], "little", signed=False)
            self.EDRSshutter = int.from_bytes(self.SetupData[776:780], "little", signed=False)
            self.PostTrigger = int.from_bytes(self.SetupData[780:784], "little", signed=False)
            self.FrameDelay = int.from_bytes(self.SetupData[784:788], "little", signed=False)
            self.bEnableColor = bool(int.from_bytes(self.SetupData[788:792], "little", signed=False))
            self.CameraVersion = int.from_bytes(self.SetupData[792:796], "little", signed=False)
            self.FirmwareVersion = int.from_bytes(self.SetupData[796:800], "little", signed=False)
            self.SoftwareVersion = int.from_bytes(self.SetupData[800:804], "little", signed=False)
            self.RecordingTimeZone = int.from_bytes(self.SetupData[804:808], "little", signed=True)
            self.CFA = int.from_bytes(self.SetupData[808:812], "little", signed=False)
            self.Bright = int.from_bytes(self.SetupData[812:816], "little", signed=True)
            self.Contrast = int.from_bytes(self.SetupData[816:820], "little", signed=True)
            self.Gamma = int.from_bytes(self.SetupData[820:824], "little", signed=True)
            self.Res21 = int.from_bytes(self.SetupData[824:828], "little", signed=False)
            self.AutoExpLevel = int.from_bytes(self.SetupData[828:832], "little", signed=False)
            self.AutoExpSpeed = int.from_bytes(self.SetupData[832:836], "little", signed=False)
            self.AutoExpRect = [
                [int.from_bytes(self.SetupData[836 + 4 * a + 8 * b:840 + 4 * a + 8 * b], "little", signed=False) for a
                 in range(2)] for b in range(2)]
            self.WBGain = [
                [struct.unpack('f', self.SetupData[852 + 4 * b + 8 * a:856 + 4 * b + 8 * a])[0] for b in range(2)] for a
                in range(4)]
            self.Rotate = int.from_bytes(self.SetupData[884:888], "little", signed=True)
            self.WBView = [struct.unpack('f', self.SetupData[888 + 4 * b:892 + 4 * b])[0] for b in range(2)]
            self.RealBPP = int.from_bytes(self.SetupData[896:900], "little", signed=False)
            self.Conv8Min = int.from_bytes(self.SetupData[900:904], "little", signed=False)
            self.Conv8Max = int.from_bytes(self.SetupData[904:908], "little", signed=False)
            self.FilterCode = int.from_bytes(self.SetupData[908:912], "little", signed=True)
            self.FilterParam = int.from_bytes(self.SetupData[912:916], "little", signed=True)
            self.UF = [int.from_bytes(self.SetupData[916:920], "little", signed=True),
                       int.from_bytes(self.SetupData[920:924], "little", signed=True),
                       int.from_bytes(self.SetupData[924:928], "little", signed=True),
                       [int.from_bytes(self.SetupData[928 + a * 4:932 + a * 4], "little", signed=True) for a in
                        range(5 * 5)]]
            self.BlackCalSVer = int.from_bytes(self.SetupData[1028:1032], "little", signed=False)
            self.WhiteCalSVer = int.from_bytes(self.SetupData[1032:1036], "little", signed=False)
            self.GrayCalSVer = int.from_bytes(self.SetupData[1036:1040], "little", signed=False)
            self.bStampTime = bool(int.from_bytes(self.SetupData[1040:1044], "little", signed=False))
            self.SoundDest = int.from_bytes(self.SetupData[1044:1048], "little", signed=False)
            self.FRPSteps = int.from_bytes(self.SetupData[1048:1052], "little", signed=False)
            self.FRPImgNr = [int.from_bytes(self.SetupData[1052 + 4 * a:1056 + 4 * a], "little", signed=True) for a in
                             range(16)]
            self.FRPRate = [int.from_bytes(self.SetupData[1116 + 4 * a:1120 + 4 * a], "little", signed=False) for a in
                            range(16)]
            self.FRPExp = [int.from_bytes(self.SetupData[1180 + 4 * a:1184 + 4 * a], "little", signed=False) for a in
                           range(16)]
            self.MCCnt = int.from_bytes(self.SetupData[1244:1248], "little", signed=True)
            self.MCPercent = [struct.unpack('f', self.SetupData[1248 + 4 * a:1252 + 4 * a])[0] for a in range(64)]
            self.CICalib = int.from_bytes(self.SetupData[1504:1508], "little", signed=False)
            self.CalibWidth = int.from_bytes(self.SetupData[1508:1512], "little", signed=False)
            self.CalibHeight = int.from_bytes(self.SetupData[1512:1516], "little", signed=False)
            self.CalibRate = int.from_bytes(self.SetupData[1516:1520], "little", signed=False)
            self.CalibExp = int.from_bytes(self.SetupData[1520:1524], "little", signed=False)
            self.CalibEDR = int.from_bytes(self.SetupData[1524:1528], "little", signed=False)
            self.CalibTemp = int.from_bytes(self.SetupData[1528:1532], "little", signed=False)
            self.HeadSerial = [int.from_bytes(self.SetupData[1532 + 4 * a:1536 + 4 * a], "little", signed=False) for a
                               in range(4)]
            self.RangeCode = int.from_bytes(self.SetupData[1548:1552], "little", signed=False)
            self.RangeSize = int.from_bytes(self.SetupData[1552:1556], "little", signed=False)
            self.Decimation = int.from_bytes(self.SetupData[1556:1560], "little", signed=False)
            self.MasterSerial = int.from_bytes(self.SetupData[1560:1564], "little", signed=False)
            self.Sensor = int.from_bytes(self.SetupData[1564:1568], "little", signed=False)
            self.ShutterNs = int.from_bytes(self.SetupData[1568:1572], "little", signed=False)
            self.EDRShutterNs = int.from_bytes(self.SetupData[1572:1576], "little", signed=False)
            self.FrameDelayNs = int.from_bytes(self.SetupData[1576:1580], "little", signed=False)
            self.ImPosXAcq = int.from_bytes(self.SetupData[1580:1584], "little", signed=False)
            self.ImPosYAcq = int.from_bytes(self.SetupData[1584:1588], "little", signed=False)
            self.ImWidthAcq = int.from_bytes(self.SetupData[1588:1592], "little", signed=False)
            self.ImHeightAcq = int.from_bytes(self.SetupData[1592:1596], "little", signed=False)
            self.Description = decode_text(self.SetupData[1596:5692])
            self.RisingEdge = bool(int.from_bytes(self.SetupData[5692:5696], "little", signed=False))
            self.FilterTime = int.from_bytes(self.SetupData[5696:5700], "little", signed=False)
            self.LongReady = bool(int.from_bytes(self.SetupData[5700:5704], "little", signed=False))
            self.ShutterOff = bool(int.from_bytes(self.SetupData[5704:5708], "little", signed=False))
            self.Res4 = [int.from_bytes(self.SetupData[5708 + a:5709 + a], "little", signed=False) for a in range(16)]
            self.bMetaWB = bool(int.from_bytes(self.SetupData[5724:5728], "little", signed=False))
            self.Hue = int.from_bytes(self.SetupData[5728:5732], "little", signed=True)
            self.BlackLevel = int.from_bytes(self.SetupData[5732:5736], "little", signed=True)
            self.WhiteLevel = int.from_bytes(self.SetupData[5736:5740], "little", signed=True)
            self.LensDescription = decode_text(self.SetupData[5740:5996])
            self.LensAperature = struct.unpack('f', self.SetupData[5996:6000])[0]
            self.LensFocusDistance = struct.unpack('f', self.SetupData[6000:6004])[0]
            self.LensFocalLength = struct.unpack('f', self.SetupData[6004:6008])[0]
            self.fOffset = struct.unpack('f', self.SetupData[6008:6012])[0]
            self.fGain = struct.unpack('f', self.SetupData[6012:6016])[0]
            self.fSaturation = struct.unpack('f', self.SetupData[6016:6020])[0]
            self.fHue = struct.unpack('f', self.SetupData[6020:6024])[0]
            self.fGamma = struct.unpack('f', self.SetupData[6024:6028])[0]
            self.fGammaR = struct.unpack('f', self.SetupData[6028:6032])[0]
            self.fGammaB = struct.unpack('f', self.SetupData[6032:6036])[0]
            self.fFlare = struct.unpack('f', self.SetupData[6036:6040])[0]
            self.fPedestalR = struct.unpack('f', self.SetupData[6040:6044])[0]
            self.fPedestalG = struct.unpack('f', self.SetupData[6044:6048])[0]
            self.fPedestalB = struct.unpack('f', self.SetupData[6048:6052])[0]
            self.fChroma = struct.unpack('f', self.SetupData[6052:6056])[0]
            self.ToneLabel = decode_text(self.SetupData[6056:6312])
            self.TonePoints = int.from_bytes(self.SetupData[6312:6316], "little", signed=True)
            self.fTone = [
                [struct.unpack('f', self.SetupData[6316 + 4 * b + 8 * a:6320 + 4 * b + 8 * a])[0] for b in range(2)] for
                a in range(32)]
            self.UserMatrixLabel = decode_text(self.SetupData[6572:6828])
            self.EnableMatricies = bool(int.from_bytes(self.SetupData[6828:6832], "little", signed=False))
            self.cmUser = [struct.unpack('f', self.SetupData[6832 + 4 * b:6836 + 4 * b])[0] for b in range(9)]
            self.EnableCrop = bool(int.from_bytes(self.SetupData[6868:6872], "little", signed=False))
            self.CropRect = [
                [int.from_bytes(self.SetupData[6872 + 4 * a + 8 * b:6876 + 4 * a + 8 * b], "little", signed=False) for a
                 in range(2)] for b in range(2)]
            self.EnableResample = bool(int.from_bytes(self.SetupData[6888:6892], "little", signed=False))
            self.ResampleWidth = int.from_bytes(self.SetupData[6892:6896], "little", signed=False)
            self.ResampleHeight = int.from_bytes(self.SetupData[6896:6900], "little", signed=False)
            self.fGain16 = struct.unpack('f', self.SetupData[6900:6904])[0]
            self.FRPShape = [int.from_bytes(self.SetupData[6904 + 4 * a:6908 + 4 * a], "little", signed=False) for a in
                             range(16)]
            self.TrigTC = int.from_bytes(self.SetupData[6968:6976], "little",
                                         signed=False)  # May be the wrong data type but correct size
            self.fPbRate = struct.unpack('f', self.SetupData[6976:6980])[0]
            self.fTcRate = struct.unpack('f', self.SetupData[6980:6984])[0]
            self.CineName = decode_text(self.SetupData[6984:7240])
            self.fGainR = struct.unpack('f', self.SetupData[7240:7244])[0]
            self.fGainG = struct.unpack('f', self.SetupData[7244:7248])[0]
            self.fGainB = struct.unpack('f', self.SetupData[7248:7252])[0]
            self.cmCalib = [struct.unpack('f', self.SetupData[7252 + 4 * a:7256 + 4 * a])[0] for a in range(9)]
            self.fWBTemp = struct.unpack('f', self.SetupData[7288:7292])[0]
            self.fWBCc = struct.unpack('f', self.SetupData[7292:7296])[0]
            self.CalibrationInfo = decode_text(self.SetupData[7296:8320])
            self.OpticalFilter = decode_text(self.SetupData[8320:9344])
            self.GpsInfo = decode_text(self.SetupData[9344:9600])
            self.Uuid = decode_text(self.SetupData[9600:9856])
            self.CreatedBy = decode_text(self.SetupData[9856:10112])
            self.RecBPP = int.from_bytes(self.SetupData[10112:10116], "little", signed=False)
            self.LowestFormatBPP = int.from_bytes(self.SetupData[10116:10118], "little", signed=False)
            self.LowestFormatQ = int.from_bytes(self.SetupData[10118:10120], "little", signed=False)
            self.fToe = struct.unpack('f', self.SetupData[10120:10124])[0]
            self.LogMode = int.from_bytes(self.SetupData[10124:10128], "little", signed=False)
            self.CameraModel = self.SetupData[10128:10384]
            self.WBType = int.from_bytes(self.SetupData[10384:10388], "little", signed=False)
            self.fDecimation = struct.unpack('f', self.SetupData[10388:10392])[0]
            self.MagSerial = int.from_bytes(self.SetupData[10392:10396], "little", signed=False)
            self.CSSerial = int.from_bytes(self.SetupData[10396:10400], "little", signed=False)
            self.dFrameRate = struct.unpack('d', self.SetupData[10400:10408])[0]
            self.SensorMode = int.from_bytes(self.SetupData[10408:10412], "little", signed=False)
            self.UndecFirst = int.from_bytes(self.SetupData[10412:10416], "little", signed=False)
            self.SupportsBinning = bool(int.from_bytes(self.SetupData[10416:10420], "little", signed=False))
            self.UvSensor = bool(int.from_bytes(self.SetupData[10420:10424], "little", signed=False))
            self.AnaDaqDescription = self.SetupData[10424:10552]
            self.BinDaqDescription = self.SetupData[10552:10680]
            self.DaqOptions = bool(int.from_bytes(self.SetupData[10680:10684], "little", signed=False))

    def SaveFramesToNewFile(self, output_filename, start_frame, end_frame):
        """Write a trimmed `.cine` containing frames `[start_frame, end_frame]`."""
        first = int(self.FileHeader.FirstImageNo)
        last = first + int(self.FileHeader.ImageCount) - 1
        if start_frame < first or end_frame > last or end_frame < start_frame:
            raise ValueError("Frame range out of bounds.")

        new_image_count = int(end_frame - start_frame + 1)
        bytes_per_offset = 8 if int(self.FileHeader.Version) == 1 else 4

        with open(output_filename, "wb") as output_file:
            new_file_header = bytearray(self.FileHeader.FileHeaderData)
            struct.pack_into("<I", new_file_header, 12, new_image_count)
            struct.pack_into("<i", new_file_header, 16, int(start_frame))
            struct.pack_into("<I", new_file_header, 20, new_image_count)
            output_file.write(new_file_header)
            output_file.write(self.ImageHeader.ImageHeaderData)
            output_file.write(self.CameraSetup.SetupData)

            offsets_start = output_file.tell()
            offset_position = offsets_start + new_image_count * bytes_per_offset
            output_offsets = []

            for frame in range(start_frame, end_frame + 1):
                idx = frame - first
                frame_start = int(self.ImageLocations.pImage[idx])
                frame_stop = int(self.ImageLocations.pImage[idx + 1])
                frame_size = frame_stop - frame_start
                output_offsets.append(offset_position)
                offset_position += frame_size

            for offset in output_offsets:
                if bytes_per_offset == 8:
                    output_file.write(struct.pack("<Q", int(offset)))
                else:
                    output_file.write(struct.pack("<I", int(offset)))

            for frame in range(start_frame, end_frame + 1):
                idx = frame - first
                frame_start = int(self.ImageLocations.pImage[idx])
                frame_stop = int(self.ImageLocations.pImage[idx + 1])
                frame_size = frame_stop - frame_start
                self.file.seek(frame_start, 0)
                output_file.write(self.file.read(frame_size))

    def AverageFrames(self, start_frame, end_frame, replace=False):
        """Compute per-pixel mean over a frame range."""
        first = int(self.FileHeader.FirstImageNo)
        last = first + int(self.FileHeader.ImageCount) - 1
        if start_frame < first or end_frame > last or end_frame < start_frame:
            raise ValueError("Frame range out of bounds.")

        acc = None
        loaded = 0
        out_dtype = np.uint16

        for frame in range(start_frame, end_frame + 1):
            self.LoadFrame(frame)
            if replace and self.PixelArray.ndim == 2:
                self.ReplaceDeadPixels()
            current = self.PixelArray
            out_dtype = current.dtype
            if acc is None:
                acc = np.zeros_like(current, dtype=np.float64)
            acc += current.astype(np.float64)
            loaded += 1

        if loaded == 0:
            raise RuntimeError("No frames were loaded successfully.")
        mean = np.rint(acc / loaded)
        return mean.astype(out_dtype)

    def ModeFrames(self, start_frame, end_frame, replace=False):
        """Robust background estimate for mono data over a frame range."""
        first = int(self.FileHeader.FirstImageNo)
        last = first + int(self.FileHeader.ImageCount) - 1
        if start_frame < first or end_frame > last:
            raise ValueError("Frame range out of bounds.")
        if end_frame < start_frame:
            raise ValueError("end_frame must be >= start_frame.")

        frames = []
        for frame in range(start_frame, end_frame + 1):
            self.LoadFrame(frame)
            if self.PixelArray.ndim != 2:
                raise ValueError("ModeFrames currently supports mono frames only.")
            if replace:
                self.ReplaceDeadPixels()
            frames.append(self.PixelArray.astype(np.float32, copy=True))

        if not frames:
            raise RuntimeError("No frames were loaded successfully.")

        stack = np.stack(frames, axis=0)
        q_bg = 0.80
        k_sigma = 2.5
        min_keep = 3

        bg = np.quantile(stack, q_bg, axis=0)
        med = np.median(stack, axis=0)
        mad = np.median(np.abs(stack - med[None, :, :]), axis=0)
        sigma = np.maximum(1.4826 * mad, 1e-6)
        keep = stack >= (bg[None, :, :] - k_sigma * sigma[None, :, :])
        num = np.sum(np.where(keep, stack, 0.0), axis=0)
        den = np.sum(keep, axis=0)
        out = np.divide(num, den, out=bg.copy(), where=(den >= min_keep))
        out = np.clip(np.rint(out), 0, np.iinfo(np.uint16).max).astype(np.uint16)
        return out

    def LoadFramesBatch(self, start_frame, count):
        """Load `count` consecutive frames into a stacked array."""
        if count <= 0:
            raise ValueError("count must be > 0")
        stop_frame = start_frame + count - 1
        first = int(self.FileHeader.FirstImageNo)
        last = first + int(self.FileHeader.ImageCount) - 1
        if start_frame < first or stop_frame > last:
            raise ValueError("Frame range out of bounds.")

        self.LoadFrame(start_frame)
        shape = self.PixelArray.shape
        dtype = self.PixelArray.dtype
        out = np.zeros(shape + (count,), dtype=dtype)
        out[..., 0] = self.PixelArray
        for i in range(1, count):
            self.LoadFrame(start_frame + i)
            out[..., i] = self.PixelArray
        return out

    @staticmethod
    def _demosaic_bilinear(frame, pattern="RGGB"):
        input_dtype = frame.dtype
        frame = frame.astype(np.float32, copy=False)
        h, w = frame.shape
        yy, xx = np.indices((h, w))
        even_r = (yy % 2) == 0
        even_c = (xx % 2) == 0

        pad = np.pad(frame, ((1, 1), (1, 1)), mode="edge")
        c = pad[1:-1, 1:-1]
        up = pad[:-2, 1:-1]
        dn = pad[2:, 1:-1]
        lf = pad[1:-1, :-2]
        rt = pad[1:-1, 2:]
        ul = pad[:-2, :-2]
        ur = pad[:-2, 2:]
        dl = pad[2:, :-2]
        dr = pad[2:, 2:]

        pattern = pattern.upper()
        if pattern == "RGGB":
            r_mask = even_r & even_c
            b_mask = (~even_r) & (~even_c)
            g_r_mask = even_r & (~even_c)
            g_b_mask = (~even_r) & even_c
        elif pattern == "BGGR":
            b_mask = even_r & even_c
            r_mask = (~even_r) & (~even_c)
            g_b_mask = even_r & (~even_c)
            g_r_mask = (~even_r) & even_c
        elif pattern == "GRBG":
            g_r_mask = even_r & even_c
            r_mask = even_r & (~even_c)
            b_mask = (~even_r) & even_c
            g_b_mask = (~even_r) & (~even_c)
        elif pattern == "GBRG":
            g_b_mask = even_r & even_c
            b_mask = even_r & (~even_c)
            r_mask = (~even_r) & even_c
            g_r_mask = (~even_r) & (~even_c)
        else:
            raise ValueError(f"Unsupported Bayer pattern: {pattern}")

        r = np.zeros_like(frame, dtype=np.float32)
        g = np.zeros_like(frame, dtype=np.float32)
        b = np.zeros_like(frame, dtype=np.float32)

        g_cross = (up + dn + lf + rt) * 0.25
        rb_diag = (ul + ur + dl + dr) * 0.25
        lr = (lf + rt) * 0.5
        ud = (up + dn) * 0.5

        r[r_mask] = c[r_mask]
        g[r_mask] = g_cross[r_mask]
        b[r_mask] = rb_diag[r_mask]

        b[b_mask] = c[b_mask]
        g[b_mask] = g_cross[b_mask]
        r[b_mask] = rb_diag[b_mask]

        g[g_r_mask] = c[g_r_mask]
        r[g_r_mask] = lr[g_r_mask]
        b[g_r_mask] = ud[g_r_mask]

        g[g_b_mask] = c[g_b_mask]
        r[g_b_mask] = ud[g_b_mask]
        b[g_b_mask] = lr[g_b_mask]

        rgb = np.stack((r, g, b), axis=-1)
        return np.rint(rgb).astype(input_dtype, copy=False)

    def GetFrameRGB(self, image_no=None, bayer_pattern="RGGB"):
        """Return the current frame as RGB, with optional simple Bayer demosaic."""
        if image_no is not None:
            self.LoadFrame(image_no)

        if self.PixelArray.ndim == 3:
            return self.PixelArray[..., ::-1].copy()
        if self.PixelArray.ndim == 2:
            return self._demosaic_bilinear(self.PixelArray, pattern=bayer_pattern)
        raise ValueError("Unsupported frame shape for RGB conversion")

    # snake_case aliases
    def open_cine_file(self, filename):
        return self.OpenCineFile(filename)

    def close_file(self):
        return self.CloseFile()

    def next_frame(self, increment=1):
        return self.NextFrame(increment=increment)

    def load_frame(self, image_no, convert_bgr_to_rgb=False):
        return self.LoadFrame(image_no, convert_bgr_to_rgb=convert_bgr_to_rgb)

    def replace_dead_pixels(self, dead_value=4095):
        return self.ReplaceDeadPixels(dead_value=dead_value)

    def save_frames_to_new_file(self, output_filename, start_frame, end_frame):
        return self.SaveFramesToNewFile(output_filename, start_frame, end_frame)

    def average_frames(self, start_frame, end_frame, replace=False):
        return self.AverageFrames(start_frame, end_frame, replace=replace)

    def mode_frames(self, start_frame, end_frame, replace=False):
        return self.ModeFrames(start_frame, end_frame, replace=replace)

    def load_frames_batch(self, start_frame, count):
        return self.LoadFramesBatch(start_frame, count)
