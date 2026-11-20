# MATLAB examples

Install the collected backend from a complete GitHub checkout or extracted
source archive before running these scripts:

```matlab
addpath('<repo>/Matlab')
install_cine_backend
```

Open a script in the MATLAB Editor, adjust the configuration at the top, and
press **Run**. Alternatively, use its full path:

```matlab
run('<repo>/Matlab/examples/basic_usage.m')
```

| Script | Features |
| --- | --- |
| [basic_usage.m](basic_usage.m) | Lazy metadata, global frame numbers, annotations, individual frames, small batches and display orientation |
| [color_processing.m](color_processing.m) | Raw Bayer samples, defect-marker repair, CFA detection and RGB demosaicing |
| [processing_and_trim.m](processing_and_trim.m) | Streaming mean, bounded background estimation, subtraction and lossless trimming |
| [streaming_write.m](streaming_write.m) | Normal/packed10 mono, RGB, known/unknown-length streams and writer cleanup |
| [images_and_video.m](images_and_video.m) | Ordered image paths and MATLAB VideoReader conversion to CINE |

The scripts generate small synthetic inputs by default. To use your own data,
set `inputFile`, `imageFiles`, or `videoFile` as appropriate. No camera recordings
or private files are required or included. Newly generated inputs and outputs
use temporary paths, printed in the Command Window; they remain available for
inspection. Choose your own output path to retain results permanently. Writers
reject existing destinations, so use a new path for each run.

`basic_usage.m` opens a figure unless `showFigure=false`. These examples use base
MATLAB functions without Image Processing or Statistics Toolbox. Video support
depends on MATLAB's installed codecs. See the [MATLAB installation guide](../README.md)
for the gateways' tested MATLAB releases and operating-system requirements;
compatibility with other releases is not established by the examples.

See the [API reference](../API.md) for reader row/channel conventions, packed10
quantization, options and memory behavior.
