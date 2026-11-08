#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <psapi.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef LONG (WINAPI *QueryThreadFn)(HANDLE,ULONG,PVOID,ULONG,PULONG);
typedef struct {DWORD id;HANDLE handle;uint64_t cpu;} Sample;
static uint64_t value(FILETIME x){return ((uint64_t)x.dwHighDateTime<<32)|x.dwLowDateTime;}
static uint64_t cpu(HANDLE h){FILETIME a,b,c,d;if(!GetThreadTimes(h,&a,&b,&c,&d))return 0;return value(c)+value(d);}
static void module(HANDLE process,void *address,char *output){
 MEMORY_BASIC_INFORMATION info;
 strcpy(output,"?");
 if(VirtualQueryEx(process,address,&info,sizeof(info)))
  GetModuleFileNameExA(process,(HMODULE)info.AllocationBase,output,1024);
}
int main(void){
 DWORD pid=0;HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
 PROCESSENTRY32 process_entry={0};process_entry.dwSize=sizeof(process_entry);
 if(Process32First(snapshot,&process_entry))do{
  if(!_stricmp(process_entry.szExeFile,"PlantsVsZombies.exe")){pid=process_entry.th32ProcessID;break;}
 }while(Process32Next(snapshot,&process_entry));
 CloseHandle(snapshot);if(!pid)return 2;
 HANDLE process=OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,FALSE,pid);
 Sample samples[256];unsigned count=0;
 snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
 THREADENTRY32 entry={0};entry.dwSize=sizeof(entry);
 if(Thread32First(snapshot,&entry))do{
  if(entry.th32OwnerProcessID!=pid || count==256)continue;
  HANDLE h=OpenThread(THREAD_ALL_ACCESS,FALSE,entry.th32ThreadID);
  if(h){samples[count]=(Sample){entry.th32ThreadID,h,cpu(h)};count++;}
 }while(Thread32Next(snapshot,&entry));
 CloseHandle(snapshot);
 QueryThreadFn query=(QueryThreadFn)GetProcAddress(GetModuleHandleA("ntdll.dll"),"NtQueryInformationThread");
 Sleep(1500);
 puts("thread_id\tcpu_ms_in_1500ms\tstart\tip\tstart_module\tip_module");
 for(unsigned i=0;i<count;i++){
  Sample s=samples[i];uint64_t delta=cpu(s.handle)-s.cpu;
  void *start=0;CONTEXT context={0};context.ContextFlags=CONTEXT_FULL;
  if(query)query(s.handle,9,&start,sizeof(start),NULL);
  SuspendThread(s.handle);BOOL ok=GetThreadContext(s.handle,&context);ResumeThread(s.handle);
  char first[1024],current[1024];module(process,start,first);module(process,(void*)context.Eip,current);
  printf("%lx\t%llu\t%p\t%08lx\t%s\t%s\n",s.id,(unsigned long long)(delta/10000),start,ok?context.Eip:0,first,current);
  CloseHandle(s.handle);
 }
 CloseHandle(process);return 0;
}
