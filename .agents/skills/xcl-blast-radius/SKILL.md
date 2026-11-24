---
name: xcl-blast-radius
description: Find what an XCL change could break outside its diff (COM vtables, Wine/vkd3d-proton boundaries, cross-thread queues, sparse/UMA memory, shader stages) and prove the safety claim by running real code. Use when reviewing or landing changes in crates/xcl/src/hle/d3d12x/ or crates/xcl/src/gpu/.
disable-model-invocation: true
---

# XCL blast radius

Find what a change breaks somewhere else before it lands. Listing grep callers is not the job; finding breakage grep cannot see is.

## Never trust a plausible writeup

State the one or two facts the change's safety depends on and push each fact as far down this ladder as is cheap. Report where you stopped:

1. Claimed in prose (worthless on its own).
2. Pointed to exact `file:line` or binary/library source.
3. Traced the failure path step by step and showed it is unreachable.
4. Ran real code (a test or probe) that fails loudly if the claim is false.
5. Verified in the running CrossOver + `vkd3d-proton` + Metal stack.

## Where grep stops in XCL

Check these boundaries explicitly when relevant to the diff:

- **COM vtable identity under Wine/vkd3d-proton:** `d3d12core.dll` asserts exact `iface->lpVtbl == &d3d12_*_vtbl` on `Resource`, `Heap`, `Fence`, `PipelineState`, `DescriptorHeap`, `RootSignature`, `CommandSignature`, and `QueryHeap` (both `this` and COM arguments). Check unadopted queues/lists (`sparse.rs`, `late_release.rs`, `vram.rs`) receiving adopted objects.
- **Lifetime and `late_release`:** never restore an extended vtable after final `Release() == 0` (use-after-free). Check `orig_fn` is never called after `UnadoptGuard::new(this)` swaps the vtable.
- **Process-wide singletons:** `real::init()`, `uma::get()`, `sparse::STATE`, and `late_release::HELD` persist across tests in one process.
- **Cross-stage recompiler changes:** an RDNA2 lowering change can fix CS while breaking VS, PS, GS, or MS (different wave32/wave64 splits, root signature ABI, or Metal subgroup support).
- **Rosetta 2 memory fragmentation:** `MEM_WRITE_WATCH` splits 16 KiB mappings into 4 KiB XNU `vm_map_entry` fragments that break `MTLDevice newBufferWithBytesNoCopy:`.

## Output

1. **What changed** (including behavior not obvious from the diff).
2. **Core safety fact** (stated plainly, ladder step reached, exact command and output).
3. **Confirmed risks** (`file:line`, failure mechanism, likelihood, repro).
4. **Checked and cleared** (boundaries verified safe and why).
5. **Before merge** (cheapest test or probe to keep).
