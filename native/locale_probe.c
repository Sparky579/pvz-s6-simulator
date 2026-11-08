/* Diagnostic: report the original Win32 ANSI file enumeration environment. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    printf("ACP=%u OEMCP=%u thread_locale=%lu user=%lu system=%lu\n",GetACP(),GetOEMCP(),GetThreadLocale(),GetUserDefaultLCID(),GetSystemDefaultLCID());
    WIN32_FIND_DATAA f;HANDLE h=FindFirstFileA("newimages/*.*",&f);
    if(h==INVALID_HANDLE_VALUE) {printf("find failed %lu\n",GetLastError());return 1;}
    unsigned count=0,missing=0;
    do {
        if(f.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)continue;
        char path[MAX_PATH+20];snprintf(path,sizeof(path),"newimages/%s",f.cFileName);
        DWORD attrs=GetFileAttributesA(path);
        if(attrs==INVALID_FILE_ATTRIBUTES)missing++;
        if(count<8) {
            printf("file ");for(const unsigned char *p=(unsigned char*)f.cFileName;*p;p++)printf("%02x",*p);
            printf(" readable=%d\n",attrs!=INVALID_FILE_ATTRIBUTES);
        }
        count++;
    }while(FindNextFileA(h,&f));
    FindClose(h);printf("files=%u missing=%u\n",count,missing);
    return 0;
}
