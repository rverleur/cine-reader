//
// Created by reesv on 6/17/2024.
//

#ifndef C_FILES_UNPACK_DATA_WIN32_H
#define C_FILES_UNPACK_DATA_WIN32_H

extern uint16_t* unpack_data_win32(uint8_t* image_data, size_t image_size, size_t* num_pixels);
extern void free_pixel_data(uint16_t* pixel_data);



#endif //C_FILES_UNPACK_DATA_WIN32_H
