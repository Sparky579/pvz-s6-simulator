static void **test_vtable;
#define S6_DISPLAY_VTABLE test_vtable
#include "../native/null_display.c"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

/* Verify every naked sink's actual x86 stack contract; a wrong ret immediate
 * corrupts the caller even if the code compiles and looks like a no-op. */
__attribute__((naked,noinline,noclone,regparm(0))) int invoke(void *fn,void *object,DWORD bytes) {
    __asm__ __volatile__(
        "push ebp\n mov ebp,esp\n push esi\n mov esi,esp\n"
        "mov eax,[ebp+16]\n sub esp,eax\n mov ecx,[ebp+12]\n call DWORD PTR [ebp+8]\n"
        "cmp esp,esi\n sete al\n movzx eax,al\n mov esp,esi\n pop esi\n pop ebp\n ret\n");
}
int main(void) {
    void **allocation=calloc(52,sizeof(void*));
    void **original=allocation+1;test_vtable=original;original[-1]=(void*)0x12345678;
    uintptr_t methods[]={0x56b8f0,0x56c740,0x56c790,0x588d60,0x5932e0,
        0x56e6a0,0x571010,0x588e70,0x585b40,0x57a160,0x57a490,0x57a610,
        0x581930,0x5858c0,0x5859f0,0x57a3d0,0x583af0};
    memcpy(original,methods,sizeof(methods));
    char *app=calloc(1,0x900),*manager=calloc(1,0x150),*image=calloc(1,0x100),*other=calloc(1,0x100);
    *(void**)(app+0x320)=manager;*(void**)(manager+0x60)=image;
    *(void***)image=original;*(void***)other=original;
    *(DWORD*)(image+0x24)=800;*(DWORD*)(image+0x28)=600;
    assert(S6NullDisplayInit(app)==0);
    void **sink=*(void***)image;
    assert(sink!=original && sink[-1]==original[-1]);
    assert(!memcmp(original,methods,sizeof(methods)) && *(void***)other==original);
    DWORD sizes[]={32,12,12,4,40,40,16,36,24,28,44,28,36,36,24,28};
    for(unsigned i=0;i<16;i++)assert(invoke(sink[i+1],image,sizes[i]));
    assert(S6NullDisplayCalls==16 && S6NullDisplayInit(app)==0);
    *(void***)image=original;*(DWORD*)(image+0x24)=640;
    assert(S6NullDisplayInit(app)==ERROR_INVALID_DATA && *(void***)image==original);
    puts("null display: all 16 stack contracts, RTTI, source-image isolation and validation passed");
    return 0;
}
