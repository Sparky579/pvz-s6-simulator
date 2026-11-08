/* Render-only sound effect log. Observes the original DSoundInstance::Play and
 * the DirectSound buffer setters; never changes what the game chooses to play.
 * Each record is 32 bytes; a SOURCE record is followed by its raw PCM bytes.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <dsound.h>
#include <stdint.h>
#include <string.h>

enum {PLAY=1,STOP=2,VOLUME=3,PAN=4,FREQUENCY=5,POSITION=6,SOURCE=7};
typedef struct {DWORD type,tick,object,source,a,b,c,d;} Record;
typedef char (__attribute__((thiscall)) *InstancePlay)(void*,DWORD,DWORD);
typedef HRESULT (WINAPI *Set)(void*,DWORD);
typedef HRESULT (WINAPI *Stop)(void*);

static HANDLE file;
static volatile DWORD *tick;
static InstancePlay previous_play;
static void **wrapped;
static Set set_position,set_volume,set_pan,set_frequency;
static Stop stop;
static void *sources[4096];
static unsigned source_count;
__declspec(dllexport) volatile DWORD SoundLogError;

static void put(const void *data,DWORD size) {
    DWORD done;
    if(!file)return;
    if(!WriteFile(file,data,size,&done,NULL) || done!=size)SoundLogError=GetLastError();
}
static void record(DWORD type,void *object,void *source,DWORD a,DWORD b,DWORD c,DWORD d) {
    Record r={type,*tick,(DWORD)(uintptr_t)object,(DWORD)(uintptr_t)source,a,b,c,d};
    put(&r,sizeof(r));
}
static void **table(void *object) {return *(void***)object;}

static void dump_source(void *source) {
    for(unsigned i=0;i<source_count;i++)if(sources[i]==source)return;
    if(source_count==4096)return;
    sources[source_count++]=source;
    typedef HRESULT (WINAPI *Format)(void*,WAVEFORMATEX*,DWORD,DWORD*);
    typedef HRESULT (WINAPI *Lock)(void*,DWORD,DWORD,void**,DWORD*,void**,DWORD*,DWORD);
    typedef HRESULT (WINAPI *Unlock)(void*,void*,DWORD,void*,DWORD);
    void **v=table(source);
    WAVEFORMATEX f={0};
    void *p1=NULL,*p2=NULL;DWORD n1=0,n2=0;
    if(FAILED(((Format)v[5])(source,&f,sizeof(f),NULL)) ||
       FAILED(((Lock)v[11])(source,0,0,&p1,&n1,&p2,&n2,DSBLOCK_ENTIREBUFFER))) {
        record(SOURCE,NULL,source,0,0,0,0);
        return;
    }
    record(SOURCE,NULL,source,n1+n2,f.nChannels,f.nSamplesPerSec,f.wBitsPerSample);
    put(p1,n1);if(p2 && n2)put(p2,n2);
    ((Unlock)v[19])(source,p1,n1,p2,n2);
}

static HRESULT WINAPI position_hook(void *o,DWORD x) {HRESULT h=set_position(o,x);if(SUCCEEDED(h))record(POSITION,o,0,x,0,0,0);return h;}
static HRESULT WINAPI volume_hook(void *o,DWORD x) {HRESULT h=set_volume(o,x);if(SUCCEEDED(h))record(VOLUME,o,0,x,0,0,0);return h;}
static HRESULT WINAPI pan_hook(void *o,DWORD x) {HRESULT h=set_pan(o,x);if(SUCCEEDED(h))record(PAN,o,0,x,0,0,0);return h;}
static HRESULT WINAPI frequency_hook(void *o,DWORD x) {HRESULT h=set_frequency(o,x);if(SUCCEEDED(h))record(FREQUENCY,o,0,x,0,0,0);return h;}
static HRESULT WINAPI stop_hook(void *o) {HRESULT h=stop(o);if(SUCCEEDED(h))record(STOP,o,0,0,0,0,0);return h;}

static void wrap(void *object) {
    void **v=table(object);
    if(wrapped==v)return;
    if(wrapped){SoundLogError=ERROR_INVALID_DATA;return;}
    DWORD old;
    if(!VirtualProtect(v,21*sizeof(void*),PAGE_EXECUTE_READWRITE,&old)){SoundLogError=GetLastError();return;}
    set_position=(Set)v[13];set_volume=(Set)v[15];set_pan=(Set)v[16];
    set_frequency=(Set)v[17];stop=(Stop)v[18];
    v[13]=position_hook;v[15]=volume_hook;v[16]=pan_hook;v[17]=frequency_hook;v[18]=stop_hook;
    DWORD ignored;VirtualProtect(v,21*sizeof(void*),old,&ignored);
    wrapped=v;
}

static char __attribute__((thiscall)) play_hook(void *instance,DWORD looping,DWORD release) {
    char ok=previous_play(instance,looping,release);
    void *source=*(void**)((char*)instance+8),*object=*(void**)((char*)instance+0xc);
    if(!ok || !object || !source)return ok;
    typedef HRESULT (WINAPI *Get)(void*,DWORD*);
    typedef HRESULT (WINAPI *Cursor)(void*,DWORD*,DWORD*);
    void **v=table(object);
    DWORD volume=0,pan=0,frequency=0,position=0;
    ((Get)v[6])(object,&volume);((Get)v[7])(object,&pan);((Get)v[8])(object,&frequency);
    ((Cursor)v[4])(object,&position,NULL);
    dump_source(source);
    record(PLAY,object,source,(looping&0xff)!=0,volume,pan,frequency);
    record(POSITION,object,0,position,0,0,0);
    wrap(object);
    return ok;
}

__declspec(dllexport) DWORD WINAPI SoundLogStart(const WCHAR *path,volatile DWORD *elapsed) {
    void **slot=(void**)0x675fbc;  /* DSoundInstance::Play */
    file=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE)return GetLastError();
    tick=elapsed;
    if(*slot!=(void*)play_hook) {
        DWORD old;
        if(!VirtualProtect(slot,4,PAGE_EXECUTE_READWRITE,&old))return GetLastError();
        previous_play=(InstancePlay)*slot;*slot=play_hook;
        DWORD ignored;VirtualProtect(slot,4,old,&ignored);
    }
    return 0;
}

__declspec(dllexport) DWORD WINAPI SoundLogFinish(void) {
    if(file && file!=INVALID_HANDLE_VALUE)CloseHandle(file);
    file=NULL;
    return SoundLogError;
}
