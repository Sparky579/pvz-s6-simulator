#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Line protocol for the Python controller. All addresses/lengths are hex. */
static HANDLE target;
static int digit(char c) {
    if(c>='0' && c<='9')return c-'0';
    if(c>='a' && c<='f')return c-'a'+10;
    if(c>='A' && c<='F')return c-'A'+10;
    return -1;
}
static unsigned decode(const char *p,unsigned char *buffer) {
    size_t length=strcspn(p,"\r\n");
    if((length&1) || length>2*1024*1024)return ~0u;
    for(unsigned i=0;i<length/2;i++) {
        int a=digit(p[2*i]),b=digit(p[2*i+1]);
        if(a<0 || b<0)return ~0u;
        buffer[i]=(unsigned char)((a<<4)|b);
    }
    return (unsigned)(length/2);
}
static DWORD word32(const unsigned char *p) {DWORD x;memcpy(&x,p,4);return x;}
static DWORD find_game(void) {
    HANDLE s = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 e = {0}; e.dwSize = sizeof(e);
    DWORD pid = 0;
    if (Process32First(s, &e)) do {
        if (!_stricmp(e.szExeFile, "PlantsVsZombies.exe")) { pid=e.th32ProcessID; break; }
    } while (Process32Next(s, &e));
    CloseHandle(s); return pid;
}
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOFBF, 1024*1024);
    DWORD pid = argc > 1 ? strtoul(argv[1], NULL, 0) : find_game();
    target = OpenProcess(PROCESS_ALL_ACCESS, FALSE, pid);
    if (!target) { printf("ERR open %lu\n", GetLastError()); return 1; }
    printf("OK %lu\n", pid);
    fflush(stdout);
    char *line = malloc(4*1024*1024);
    unsigned char *buf = malloc(1024*1024);
    char *hex = malloc(2*1024*1024);
    static const char digits[]="0123456789abcdef";
    while (fgets(line, 4*1024*1024, stdin)) {
        char op=0; unsigned long a=0,n=0; SIZE_T done=0;
        sscanf(line,"%c %lx %lx", &op,&a,&n);
        if (op=='R' && n<=1024*1024) {
            if (!ReadProcessMemory(target,(void*)a,buf,n,&done)) goto error;
            for (SIZE_T j=0;j<done;j++) {
                hex[j*2]=digits[buf[j]>>4];hex[j*2+1]=digits[buf[j]&15];
            }
            fputs("OK ",stdout);fwrite(hex,2,done,stdout);putchar('\n');
        } else if (op=='W' || op=='B') {
            char *p=strchr(line,' '); p=p?strchr(p+1,' '):NULL;
            if (!p) goto error;
            n=decode(p+1,buf);
            if(n==~0u) {SetLastError(ERROR_INVALID_DATA);goto error;}
            if(op=='W') {
                DWORD old; VirtualProtectEx(target,(void*)a,n,PAGE_EXECUTE_READWRITE,&old);
                if(!WriteProcessMemory(target,(void*)a,buf,n,&done)) goto error;
                FlushInstructionCache(target,(void*)a,n);
            } else {
                if(n<4) {SetLastError(ERROR_INVALID_DATA);goto error;}
                DWORD count=word32(buf),offset=4;
                if(count>10000) {SetLastError(ERROR_INVALID_DATA);goto error;}
                for(DWORD j=0;j<count;j++) {
                    if(offset+8>n) {SetLastError(ERROR_INVALID_DATA);goto error;}
                    DWORD address=word32(buf+offset),size=word32(buf+offset+4),old;
                    offset+=8;
                    if(size>n-offset) {SetLastError(ERROR_INVALID_DATA);goto error;}
                    VirtualProtectEx(target,(void*)address,size,PAGE_EXECUTE_READWRITE,&old);
                    if(!WriteProcessMemory(target,(void*)address,buf+offset,size,&done)) goto error;
                    offset+=size;
                }
                if(offset!=n) {SetLastError(ERROR_INVALID_DATA);goto error;}
                FlushInstructionCache(target,NULL,0);
            }
            puts("OK");
        } else if (op=='A') {
            void *p=VirtualAllocEx(target,(void*)a,n,MEM_RESERVE|MEM_COMMIT,PAGE_EXECUTE_READWRITE);
            if (!p) goto error;
            printf("OK %lx\n",(unsigned long)p);
        } else if (op=='T') {
            HANDLE t=CreateRemoteThread(target,NULL,0,(LPTHREAD_START_ROUTINE)a,NULL,0,NULL);
            if(!t) goto error;
            DWORD w=WaitForSingleObject(t,n?n:30000),code=0;
            GetExitCodeThread(t,&code);CloseHandle(t);printf("OK %lx %lx\n",w,code);
        } else if (op=='C') {
            HANDLE s=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
            THREADENTRY32 e={0};e.dwSize=sizeof(e);DWORD tid=0;
            if(Thread32First(s,&e)) do {
                if(e.th32OwnerProcessID==pid) { tid=e.th32ThreadID;break; }
            } while(Thread32Next(s,&e));
            CloseHandle(s);
            HANDLE t=OpenThread(THREAD_ALL_ACCESS,FALSE,tid);
            if(!t) goto error;
            SuspendThread(t);CONTEXT c={0};c.ContextFlags=CONTEXT_FULL;
            BOOL ok=GetThreadContext(t,&c);ResumeThread(t);CloseHandle(t);
            if(!ok) goto error;
            printf("OK tid=%lx eip=%lx esp=%lx ebp=%lx eax=%lx ebx=%lx ecx=%lx edx=%lx esi=%lx edi=%lx\n",
                   tid,c.Eip,c.Esp,c.Ebp,c.Eax,c.Ebx,c.Ecx,c.Edx,c.Esi,c.Edi);
        } else if (op=='L') {
            DWORD app=0;HWND window=NULL;
            if(!ReadProcessMemory(target,(void*)0x6a9ec0,&app,4,&done)) goto error;
            if(!app || !ReadProcessMemory(target,(void*)(app+0x350),&window,4,&done)) goto error;
            PostMessage(window,WM_MOUSEMOVE,0,MAKELPARAM(a,n));
            PostMessage(window,WM_LBUTTONDOWN,MK_LBUTTON,MAKELPARAM(a,n));
            PostMessage(window,WM_LBUTTONUP,0,MAKELPARAM(a,n));
            puts("OK");
        } else if (op=='Q') { puts("OK");fflush(stdout);break; }
        else { puts("ERR protocol");fflush(stdout);continue; }
        fflush(stdout);
        continue;
        error: printf("ERR %lu\n",GetLastError());fflush(stdout);
    }
    CloseHandle(target);free(line);free(buf);free(hex);return 0;
}
