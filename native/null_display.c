/* Virtual display sink. Only the final screen image discards raster writes.
 * All original widgets, graphics geometry, source-image caches and CT draw
 * callbacks still execute. The original RTTI and non-raster methods stay intact.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <string.h>

__declspec(dllexport) volatile DWORD S6NullDisplayCalls;
static struct {void *rtti;void *methods[51];} screen_table;
static BOOL initialized;
#ifndef S6_DISPLAY_VTABLE
#define S6_DISPLAY_VTABLE ((void**)0x67238c)
#endif
#define SINK(name,n) __attribute__((naked)) static void name(void) { \
 __asm__ __volatile__("pushfd\n inc DWORD PTR [_S6NullDisplayCalls]\n popfd\n ret " #n "\n"); }
SINK(sink4,4)
SINK(sink12,12)
SINK(sink16,16)
SINK(sink24,24)
SINK(sink28,28)
SINK(sink36,36)
SINK(sink40,40)
SINK(sink44,44)
__attribute__((naked)) static void sink_poly32(void) {
    __asm__ __volatile__("pushfd\n inc DWORD PTR [_S6NullDisplayCalls]\n popfd\n mov eax,1\n ret 32\n");
}

__declspec(dllexport) DWORD WINAPI S6NullDisplayInit(void *app) {
    void *manager=*(void**)((char*)app+0x320);
    if(!manager)return ERROR_INVALID_DATA;
    void *image=*(void**)((char*)manager+0x60);
    if(!image)return ERROR_INVALID_DATA;
    void **original=*(void***)image;
    if(original==screen_table.methods)return 0;
    if(original!=S6_DISPLAY_VTABLE)return ERROR_INVALID_DATA;
    if(*(DWORD*)((char*)image+0x24)!=800 || *(DWORD*)((char*)image+0x28)!=600)
        return ERROR_INVALID_DATA;
    static const uintptr_t expected[]={0x56b8f0,0x56c740,0x56c790,0x588d60,0x5932e0,
        0x56e6a0,0x571010,0x588e70,0x585b40,0x57a160,0x57a490,0x57a610,
        0x581930,0x5858c0,0x5859f0,0x57a3d0,0x583af0};
    if(memcmp(original,expected,sizeof(expected)))return ERROR_INVALID_DATA;
    if(!initialized) {
        screen_table.rtti=original[-1];memcpy(screen_table.methods,original,sizeof(screen_table.methods));
        void *raster[]={sink_poly32,sink12,sink12,sink4,sink40,sink40,sink16,sink36,
                       sink24,sink28,sink44,sink28,sink36,sink36,sink24,sink28};
        memcpy(screen_table.methods+1,raster,sizeof(raster));initialized=TRUE;
    }
    *(void***)image=screen_table.methods;
    return 0;
}
