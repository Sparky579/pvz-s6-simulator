"""Prototype: run the original CT overlay each frame, omit scene raster setup."""


def install(engine,no_lock=True):
    e=engine;m=e.memory
    # Board::Draw is a thiscall with one Graphics* stack argument. The original
    # 41A2A0 overlay takes Board* on the stack and Graphics* in EDI; it executes
    # the full CT 1316 callback, including target/latch writes, every frame.
    slot=0x656ca8+0x68
    if m.u32(slot)!=0x41acf0:raise RuntimeError('Unexpected original Board::Draw entry')
    target=e.BASE+0xd000
    m.write(target,e.asm('pushad;mov edi,dword ptr [esp+36];push ecx;call 0x41a2a0;popad;ret 4',target))
    m.put32(slot,target)
    if no_lock:
        # DrawScreen still invokes every widget callback. Its surface-lock
        # result only controls a matching UnlockSurface; the screen sink has
        # no pixels to lock. Source images keep their own original locks.
        screen=m.u32(m.u32(e.lawn+0x320)+0x60);table=m.u32(screen)
        if m.u32(table+47*4)!=0x56ba70:raise RuntimeError('Unexpected screen surface lock')
        lock=e.BASE+0xd800;m.write(lock,e.asm('xor eax,eax;ret',lock))
        m.put32(table+47*4,lock)
