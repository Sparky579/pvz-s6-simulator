/* Diagnostic observer only: never handles, skips, or repairs an exception. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <string.h>

typedef struct Snapshot {
    DWORD ready,code,address,thread;
    DWORD eax,ebx,ecx,edx,esi,edi,ebp,esp,eip,eflags;
    DWORD access,address_accessed,stack_bytes;
    DWORD stack[128];
} Snapshot;
__declspec(dllexport) volatile LONG S6ExceptionCount;
__declspec(dllexport) Snapshot S6Exceptions[32];
static PVOID observer;

static LONG CALLBACK observe(EXCEPTION_POINTERS *p) {
    DWORD code=p->ExceptionRecord->ExceptionCode;
    if(code!=EXCEPTION_ACCESS_VIOLATION && code!=EXCEPTION_ILLEGAL_INSTRUCTION &&
       code!=EXCEPTION_INT_DIVIDE_BY_ZERO && code!=EXCEPTION_STACK_OVERFLOW)
        return EXCEPTION_CONTINUE_SEARCH;
    LONG index=InterlockedIncrement(&S6ExceptionCount)-1;
    if(index>=32)return EXCEPTION_CONTINUE_SEARCH;
    Snapshot *s=&S6Exceptions[index];CONTEXT *c=p->ContextRecord;
    s->code=code;s->address=(DWORD)(uintptr_t)p->ExceptionRecord->ExceptionAddress;
    s->thread=GetCurrentThreadId();
    s->eax=c->Eax;s->ebx=c->Ebx;s->ecx=c->Ecx;s->edx=c->Edx;
    s->esi=c->Esi;s->edi=c->Edi;s->ebp=c->Ebp;s->esp=c->Esp;
    s->eip=c->Eip;s->eflags=c->EFlags;
    if(p->ExceptionRecord->NumberParameters>=2) {
        s->access=p->ExceptionRecord->ExceptionInformation[0];
        s->address_accessed=p->ExceptionRecord->ExceptionInformation[1];
    }
    SIZE_T read=0;
    ReadProcessMemory(GetCurrentProcess(),(void*)(uintptr_t)c->Esp,s->stack,sizeof(s->stack),&read);
    s->stack_bytes=(DWORD)read;
    MemoryBarrier();s->ready=1;
    return EXCEPTION_CONTINUE_SEARCH;
}
__declspec(dllexport) DWORD WINAPI S6ObserveInit(void) {
    if(observer)return 0;
    observer=AddVectoredExceptionHandler(1,observe);
    return observer?0:GetLastError();
}
