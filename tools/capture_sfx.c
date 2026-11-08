/* Observe original DirectSound PCM and controls without changing the clock.
 * The original adapter is included unchanged, under a separate DLL name so
 * historical executor fingerprints and binaries remain intact. */
#define s6_register_instance original_register_instance
#include "../native/audio_clock.c"
#undef s6_register_instance
#include <stdio.h>
#include <wchar.h>

typedef struct Sample {
    void *source;
    DWORD id, game_id;
    struct Sample *next;
} Sample;
typedef struct Voice {
    void *object;
    DWORD id;
    Sample *sample;
    struct Voice *next;
} Voice;
typedef struct ExtraTable {
    void **address;
    SetFn volume, pan;
} ExtraTable;
static ExtraTable extra_tables[8];
static unsigned extra_count;
static Sample *samples;
static Voice *voices;
static DWORD sample_count,voice_count,origin;
static FILE *sample_file,*event_file,*name_file;
static void *sound_manager;
static BOOL recording;
__declspec(dllexport) DWORD S6CaptureError;

static Voice *get_voice(void *object) {
    for(Voice *v=voices;v;v=v->next)if(v->object==object)return v;
    return NULL;
}
static ExtraTable *get_extra(void *object) {
    void **v=*(void***)object;
    for(unsigned i=0;i<extra_count;i++)if(extra_tables[i].address==v)return extra_tables+i;
    return NULL;
}
static void event(Voice *v,DWORD op,DWORD a,DWORD b,DWORD c,DWORD d) {
    if(!recording || !v || S6CaptureError)return;
    DWORD record[]={*game_tick-origin,op,v->id,v->sample->id,a,b,c,d};
    if(fwrite(record,sizeof(record),1,event_file)!=1)S6CaptureError=ERROR_WRITE_FAULT;
}
static void start_event(Voice *v) {
    if(!v)return;
    Buffer *b=find_buffer(v->object);
    if(!b || !b->playing)return;
    typedef HRESULT (WINAPI *GetLong)(void*,LONG*);
    void **table=*(void***)v->object;
    LONG volume=0,pan=0;
    HRESULT hr=((GetLong)table[6])(v->object,&volume);
    if(SUCCEEDED(hr))hr=((GetLong)table[7])(v->object,&pan);
    if(FAILED(hr)){S6CaptureError=hr;return;}
    uint64_t position=b->position+(uint64_t)(*game_tick-b->tick)*b->frequency;
    if(b->limit && position>=b->limit) {
        if(b->looping)position%=b->limit;
        else return;
    }
    event(v,1|(b->looping?0x100:0),(DWORD)position,b->frequency,(DWORD)volume,(DWORD)pan);
}
static HRESULT WINAPI capture_play(void *object,DWORD r,DWORD p,DWORD flags) {
    HRESULT hr=play_hook(object,r,p,flags);
    if(SUCCEEDED(hr))start_event(get_voice(object));
    return hr;
}
static HRESULT WINAPI capture_stop(void *object) {
    HRESULT hr=stop_hook(object);
    if(SUCCEEDED(hr))event(get_voice(object),2,0,0,0,0);
    return hr;
}
static HRESULT WINAPI capture_position(void *object,DWORD value) {
    HRESULT hr=position_hook(object,value);
    Buffer *b=find_buffer(object);
    if(SUCCEEDED(hr) && b)event(get_voice(object),3,(DWORD)b->position,0,0,0);
    return hr;
}
static HRESULT WINAPI capture_frequency(void *object,DWORD value) {
    HRESULT hr=frequency_hook(object,value);
    Buffer *b=find_buffer(object);
    if(SUCCEEDED(hr) && b)event(get_voice(object),4,b->frequency,0,0,0);
    return hr;
}
static HRESULT WINAPI capture_volume(void *object,DWORD value) {
    HRESULT hr=get_extra(object)->volume(object,value);
    if(SUCCEEDED(hr))event(get_voice(object),5,value,0,0,0);
    return hr;
}
static HRESULT WINAPI capture_pan(void *object,DWORD value) {
    HRESULT hr=get_extra(object)->pan(object,value);
    if(SUCCEEDED(hr))event(get_voice(object),6,value,0,0,0);
    return hr;
}
static ULONG WINAPI capture_release(void *object) {
    ULONG count=release_hook(object);
    if(!count) {
        Voice **p=&voices;
        while(*p && (*p)->object!=object)p=&(*p)->next;
        if(*p){Voice *v=*p;event(v,2,0,0,0,0);*p=v->next;free(v);}
    }
    return count;
}
static BOOL install_capture(void *object) {
    if(get_extra(object))return TRUE;
    if(extra_count==8){S6CaptureError=ERROR_TOO_MANY_NAMES;return FALSE;}
    void **v=*(void***)object;
    ExtraTable *t=extra_tables+extra_count++;
    t->address=v;t->volume=(SetFn)v[15];t->pan=(SetFn)v[16];
    DWORD old,ignored;
    if(!VirtualProtect(v,21*sizeof(void*),PAGE_EXECUTE_READWRITE,&old))return FALSE;
    v[2]=capture_release;v[12]=capture_play;v[13]=capture_position;
    v[15]=capture_volume;v[16]=capture_pan;v[17]=capture_frequency;v[18]=capture_stop;
    VirtualProtect(v,21*sizeof(void*),old,&ignored);return TRUE;
}
static Sample *read_sample(void *source,void *object) {
    for(Sample *s=samples;s;s=s->next)if(s->source==source)return s;
    typedef HRESULT (WINAPI *CapsFn)(void*,DSBCAPS*);
    typedef HRESULT (WINAPI *FormatFn)(void*,WAVEFORMATEX*,DWORD,DWORD*);
    typedef HRESULT (WINAPI *LockFn)(void*,DWORD,DWORD,void**,DWORD*,void**,DWORD*,DWORD);
    typedef HRESULT (WINAPI *UnlockFn)(void*,void*,DWORD,void*,DWORD);
    void **v=*(void***)object;
    DSBCAPS caps={0};caps.dwSize=sizeof(caps);
    WAVEFORMATEX fmt={0};void *p1=NULL,*p2=NULL;DWORD n1=0,n2=0;
    HRESULT hr=((CapsFn)v[3])(object,&caps);
    if(SUCCEEDED(hr))hr=((FormatFn)v[5])(object,&fmt,sizeof(fmt),NULL);
    if(FAILED(hr) || fmt.wFormatTag!=WAVE_FORMAT_PCM ||
       (fmt.wBitsPerSample!=8 && fmt.wBitsPerSample!=16) ||
       (fmt.nChannels!=1 && fmt.nChannels!=2)) {
        S6CaptureError=FAILED(hr)?hr:ERROR_INVALID_DATA;return NULL;
    }
    hr=((LockFn)v[11])(object,0,0,&p1,&n1,&p2,&n2,DSBLOCK_ENTIREBUFFER);
    if(FAILED(hr)){S6CaptureError=hr;return NULL;}
    Sample *s=calloc(1,sizeof(*s));
    if(!s){S6CaptureError=ERROR_OUTOFMEMORY;return NULL;}
    s->source=source;s->id=++sample_count;s->game_id=~0u;s->next=samples;samples=s;
    for(DWORD i=0;i<256;i++)if(*(void**)((char*)sound_manager+4+i*4)==source){s->game_id=i;break;}
    DWORD header[]={s->id,s->game_id,fmt.nSamplesPerSec,fmt.nChannels,
                    fmt.wBitsPerSample,fmt.nBlockAlign,n1+n2,fmt.wFormatTag};
    if(fwrite(header,sizeof(header),1,sample_file)!=1 ||
       fwrite(p1,1,n1,sample_file)!=n1 || (n2 && fwrite(p2,1,n2,sample_file)!=n2))
        S6CaptureError=ERROR_WRITE_FAULT;
    ((UnlockFn)v[19])(object,p1,n1,p2,n2);
    char name[512]="unknown";
    if(s->game_id<256) {
        char *str=(char*)sound_manager+0x404+s->game_id*28;
        DWORD size=*(DWORD*)(str+20),capacity=*(DWORD*)(str+24);
        if(size<sizeof(name)) {
            char *text=capacity<=15?str+4:*(char**)(str+4);
            memcpy(name,text,size);name[size]=0;
        }
    }
    fprintf(name_file,"%lu\t%lu\t%s\n",s->id,s->game_id,name);
    return s;
}
void __cdecl s6_register_instance(void *instance) {
    original_register_instance(instance);
    void *object=*(void**)((char*)instance+0xc);
    if(!object || !sample_file || S6CaptureError)return;
    if(!get_voice(object)) {
        Sample *s=read_sample(*(void**)((char*)instance+8),object);
        if(!s)return;
        Voice *v=calloc(1,sizeof(*v));
        if(!v){S6CaptureError=ERROR_OUTOFMEMORY;return;}
        v->object=object;v->id=++voice_count;v->sample=s;v->next=voices;voices=v;
    }
    if(!install_capture(object))S6CaptureError=GetLastError();
}

__declspec(dllexport) DWORD WINAPI CaptureSfxInit(void *app,const WCHAR *directory) {
    DWORD result=S6AudioInit(app);
    if(result)return result;
    sound_manager=*(void**)((char*)app+0x4b4);
    WCHAR path[2048];
    swprintf(path,2048,L"%ls\\samples.bin",directory);sample_file=_wfopen(path,L"wb");
    swprintf(path,2048,L"%ls\\events.bin",directory);event_file=_wfopen(path,L"wb");
    swprintf(path,2048,L"%ls\\sample-names.tsv",directory);name_file=_wfopen(path,L"wb");
    if(!sample_file || !event_file || !name_file)return ERROR_OPEN_FAILED;
    setvbuf(sample_file,NULL,_IOFBF,65536);setvbuf(event_file,NULL,_IOFBF,65536);
    return 0;
}
__declspec(dllexport) void WINAPI CaptureSfxBegin(void) {
    origin=*game_tick;recording=TRUE;
    for(Voice *v=voices;v;v=v->next)start_event(v);
}
__declspec(dllexport) void WINAPI CaptureSfxClose(void) {
    recording=FALSE;
    if(sample_file){fclose(sample_file);sample_file=NULL;}
    if(event_file){fclose(event_file);event_file=NULL;}
    if(name_file){fclose(name_file);name_file=NULL;}
}
