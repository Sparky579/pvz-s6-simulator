/* Offline capture of the original 800x600 DirectDraw surface. No game rules. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ddraw.h>
#include <stdint.h>
#include <string.h>

#define WIDTH 800
#define HEIGHT 600
#define PIXELS (WIDTH*HEIGHT*4)
#define STRIDE (PIXELS+8)
static HANDLE file, mapping;
static unsigned char *buffer;
static DWORD capacity;
static void *image, *sink_table, *fast_draw;
static char *board;
static int board_x;
typedef unsigned char (__attribute__((thiscall)) *SurfaceMethod)(void*);

__declspec(dllexport) DWORD WINAPI CaptureInit(void *app, const WCHAR *path,
                                             DWORD count, void *fast) {
    image=*(void**)((char*)*(void**)((char*)app+0x320)+0x60);
    if(!image || *(DWORD*)((char*)image+0x24)!=WIDTH ||
       *(DWORD*)((char*)image+0x28)!=HEIGHT)return ERROR_INVALID_DATA;
    sink_table=*(void**)image;fast_draw=fast;capacity=count;
    board=*(char**)((char*)app+0x768);board_x=*(int*)(board+0x30);
    file=CreateFileW(path,GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,
                     NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE)return GetLastError();
    mapping=CreateFileMappingW(file,NULL,PAGE_READWRITE,0,64+capacity*STRIDE,NULL);
    if(!mapping)return GetLastError();
    buffer=MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,0);
    if(!buffer)return GetLastError();
    memset(buffer,0,64);return 0;
}

__declspec(dllexport) void WINAPI CaptureSelect(DWORD enabled) {
    *(void**)image=enabled ? (void*)0x67238c : sink_table;
    *(void**)0x656d10=enabled ? (void*)0x41acf0 : fast_draw;
    /* The headless setup leaves the seed-selection camera at -380. Center
     * only while drawing, then restore it before the next gameplay update. */
    *(int*)(board+0x30)=enabled ? 0 : board_x;
}

__declspec(dllexport) void WINAPI CaptureReset(void) {
    *(DWORD*)(buffer+4)=0;
}

__declspec(dllexport) void WINAPI CaptureFrame(DWORD frame) {
    DWORD count=*(DWORD*)(buffer+4);
    if(*(DWORD*)buffer)return;
    if(count>=capacity){*(DWORD*)buffer=ERROR_BUFFER_OVERFLOW;return;}
    SurfaceMethod lock=(SurfaceMethod)0x56ba70,unlock=(SurfaceMethod)0x56bad0;
    if(!lock(image)){*(DWORD*)buffer=ERROR_LOCK_FAILED;return;}
    DDSURFACEDESC *desc=(DDSURFACEDESC*)((char*)image+0x80);
    DWORD bpp=desc->ddpfPixelFormat.dwRGBBitCount;
    *(DWORD*)(buffer+8)=desc->dwWidth;*(DWORD*)(buffer+12)=desc->dwHeight;
    *(DWORD*)(buffer+16)=bpp;
    if(bpp!=32 || desc->dwWidth!=WIDTH || desc->dwHeight!=HEIGHT || !desc->lpSurface) {
        *(DWORD*)buffer=ERROR_INVALID_DATA;unlock(image);return;
    }
    unsigned char *dest=buffer+64+count*STRIDE;
    *(DWORD*)dest=frame;*(DWORD*)(dest+4)=0;
    for(DWORD y=0;y<HEIGHT;y++)
        memcpy(dest+8+y*WIDTH*4,(char*)desc->lpSurface+y*desc->lPitch,WIDTH*4);
    unlock(image);*(DWORD*)(buffer+4)=count+1;
    *(int*)(board+0x30)=board_x;
}

__declspec(dllexport) void WINAPI CaptureClose(void) {
    *(void**)image=(void*)0x67238c;*(void**)0x656d10=(void*)0x41acf0;
    *(int*)(board+0x30)=board_x;
    if(buffer)UnmapViewOfFile(buffer);
    if(mapping)CloseHandle(mapping);
    if(file && file!=INVALID_HANDLE_VALUE)CloseHandle(file);
}
