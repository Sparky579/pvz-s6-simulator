/* Exercise the device adapter without an actual sound card or game process. */
#include "../native/audio_clock.c"
#include <stdio.h>
#include <assert.h>

typedef struct Fake {void **vtable;DWORD frequency,status,cursor;unsigned plays;} Fake;
static HRESULT WINAPI fake_status(void *p,DWORD *s) {
    if(!s)return DSERR_INVALIDPARAM;
    *s=((Fake*)p)->status;return S_OK;
}
static HRESULT WINAPI fake_play(void *p,DWORD a,DWORD b,DWORD f) {
    ((Fake*)p)->plays++;return S_OK;
}
static HRESULT WINAPI fake_stop(void *p) {return S_OK;}
static HRESULT WINAPI fake_position(void *p,DWORD n) {((Fake*)p)->cursor=n;return S_OK;}
static HRESULT WINAPI fake_frequency(void *p,DWORD n) {((Fake*)p)->frequency=n;return S_OK;}
static HRESULT WINAPI fake_get_frequency(void *p,DWORD *n) {*n=((Fake*)p)->frequency;return S_OK;}
static HRESULT WINAPI fake_caps(void *p,DSBCAPS *c) {c->dwBufferBytes=4000;return S_OK;}
static HRESULT WINAPI fake_format(void *p,WAVEFORMATEX *f,DWORD n,DWORD *needed) {
    memset(f,0,sizeof(*f));f->nBlockAlign=4;return S_OK;
}
static HRESULT WINAPI fake_cursor(void *p,DWORD *play,DWORD *write) {
    if(play)*play=333;
    if(write)*write=777;
    return S_OK;
}
static ULONG WINAPI fake_release(void *p) {return 0;}

int main(void) {
    DWORD tick=0;game_tick=&tick;InitializeCriticalSection(&guard);
    void *v[21]={0};v[2]=fake_release;v[3]=fake_caps;v[4]=fake_cursor;
    v[5]=fake_format;v[8]=fake_get_frequency;v[9]=fake_status;v[12]=fake_play;
    v[13]=fake_position;v[17]=fake_frequency;v[18]=fake_stop;
    Fake object={v,1000,0,0,0};unsigned char instance[32]={0};
    *(void**)(instance+0xc)=&object;s6_register_instance(instance);
    assert(!S6AudioError && find_buffer(&object));
    assert(play_hook(&object,0,0,0)==S_OK && !object.plays);
    tick=49;DWORD status=0,pos=0;
    assert(status_hook(&object,&status)==S_OK && (status&DSBSTATUS_PLAYING));
    assert(cursor_hook(&object,&pos,NULL)==S_OK && pos==1960);
    tick=100;status_hook(&object,&status);assert(!(status&DSBSTATUS_PLAYING));
    assert(position_hook(&object,0)==S_OK);
    assert(play_hook(&object,0,0,DSBPLAY_LOOPING)==S_OK);
    tick=250;status_hook(&object,&status);cursor_hook(&object,&pos,NULL);
    assert((status&(DSBSTATUS_PLAYING|DSBSTATUS_LOOPING))==(DSBSTATUS_PLAYING|DSBSTATUS_LOOPING));
    assert(pos==2000);
    frequency_hook(&object,2000);tick=275;cursor_hook(&object,&pos,NULL);assert(pos==0);
    stop_hook(&object);tick=300;status_hook(&object,&status);assert(!(status&DSBSTATUS_PLAYING));
    position_hook(&object,400);tick=325;cursor_hook(&object,&pos,NULL);assert(pos==400);
    object.status=DSBSTATUS_BUFFERLOST;
    assert(play_hook(&object,0,0,0)==DSERR_BUFFERLOST);
    assert(status_hook(&object,NULL)==DSERR_INVALIDPARAM);
    object.status=0;S6AudioPhysicalOutput=1;
    assert(play_hook(&object,0,0,0)==S_OK && object.plays==1);
    S6AudioPhysicalOutput=0;
    find_buffer(&object)->tick=0xfffffff0;tick=0x10;
    cursor_hook(&object,&pos,NULL);assert(pos==2960);
    assert(release_hook(&object)==0 && !find_buffer(&object));
    /* A shared vtable must leave unrelated music/unregistered buffers alone. */
    Fake other={v,1000,DSBSTATUS_PLAYING,0,0};
    assert(play_hook(&other,0,0,0)==S_OK && other.plays==1);
    status_hook(&other,&status);assert(status==DSBSTATUS_PLAYING);
    cursor_hook(&other,&pos,NULL);assert(pos==333);
    assert(sound_milliseconds()==0x10*10);
    tick=0xffffffffu;assert(sound_milliseconds()==0xfffffff6u);
    puts("audio adapter: duration, loop, pitch, stop, cursor, errors, wrap and delegation passed");
    return 0;
}
