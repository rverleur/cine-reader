#ifndef CINE_CORE_H
#define CINE_CORE_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* ABI 1. Strings/paths are UTF-8. Handles must not be used concurrently.
 * Caller owns all output buffers. Input/output memory must not overlap.
 * Functions return 0 or -1; last_error is
 * thread local and valid until the next call on that thread. */
typedef struct {
    uint32_t width;
    int32_t height;
    uint32_t bit_count, compression, real_bpp, cfa, frame_count;
    int32_t first_frame;
    uint32_t channels, sample_bytes;
    uint64_t decoded_bytes, file_size;
} CineInfo;
typedef struct {
    uint32_t annotation_size, image_size;
} CineFrameInfo;
typedef struct {
    uint32_t width, height, channels, bit_depth, packed10, frame_count;
    int32_t first_frame;
    uint32_t cfa;
    double frame_rate;
} CineWriterOptions;
uint32_t cine_abi_version(void);
const char *cine_last_error(void);
void *cine_reader_open(const char *path);
void cine_reader_close(void *reader);
int32_t cine_reader_info(void *reader, CineInfo *info);
/* index is zero based; index==frame_count returns the file-size sentinel. */
int32_t cine_reader_offset(void *reader, uint32_t index, uint64_t *offset);
/* kind: 0 file header, 1 bitmap, 2 fixed setup, 3 last annotation,
 * 4 last payload, 5 setup plus tagged blocks, 6 raw offset table.
 * Query with out=NULL, capacity=0; written receives required bytes. */
int32_t cine_reader_block(void *reader, uint32_t kind, uint8_t *out, size_t capacity, size_t *written);
int32_t cine_reader_read_at(void *reader, uint64_t offset, uint8_t *out, size_t length);
/* flags: 1 canonical top-down rows, 2 RGB instead of BGR.
 * flags=0 preserves the legacy bindings' storage row order and BGR. */
int32_t cine_reader_read_frame(void *reader, uint32_t index, uint32_t flags, uint8_t *out, size_t capacity, CineFrameInfo *info);
int32_t cine_reader_trim(void *reader, const char *path, uint32_t start_index, uint32_t count);
/* Standalone payload decoding: compression=0 normal, 256 P10, 1024 P12L. */
int32_t cine_decode(const uint8_t *data, size_t length, uint32_t width, int32_t height, uint32_t bit_count, uint32_t compression, uint32_t flags, uint8_t *out, size_t capacity);
int32_t cine_unpack10(const uint8_t *data, size_t length, uint16_t *out, size_t samples);
void *cine_writer_create(const char *path, const CineWriterOptions *options);
int32_t cine_writer_write(void *writer, const uint8_t *data, size_t length);
/* Image frontend: packed10 accepts u8/u16 mono or RGB, scaling u8 to 12-bit
 * and sampling RGB into the configured Bayer CFA. Normal input is unchanged. */
int32_t cine_writer_write_image(void *writer, const uint8_t *data, size_t length, uint32_t sample_bytes, uint32_t channels);
/* finish publishes output; close releases the handle and aborts unfinished files. */
int32_t cine_writer_finish(void *writer);
void cine_writer_close(void *writer);
/* Row-major processing. sample_type: 1=u8, 2=u16, 4=f32, 8=f64.
 * op: 1 repair, 2 same-Bayer-phase repair, 3 demosaic.
 * param for repair: 0 equality, 1 threshold. value=dead value.
 * param for demosaic: 0 RGGB, 1 BGGR, 2 GRBG, 3 GBRG.
 * param bit256 selects MATLAB rounding (ties away from zero).
 * Demosaic output has 3 channels; otherwise output matches input shape. */
int32_t cine_process(const void *src, void *dst, uint32_t width, uint32_t height, uint32_t channels, uint32_t sample_type, uint32_t op, uint32_t param, double value);
/* Streaming statistics on f64 input arrays; Rust owns the accumulator.
 * mode: 0 mean, 1 top-k, 2 quantile/MAD. k=retained samples for top-k.
 * mode bit256 selects MATLAB rounding and quantile interpolation.
 * MAD intentionally stores its stack; mean and top-k are bounded. */
void *cine_stats_create(size_t samples, uint32_t mode, uint32_t k, double q, double sigma, uint32_t min_keep);
int32_t cine_stats_push(void *stats, const double *values, size_t samples);
int32_t cine_stats_finish(void *stats, double *out, size_t samples, uint64_t *count);
void cine_stats_close(void *stats);
#ifdef __cplusplus
}
#endif
#endif
