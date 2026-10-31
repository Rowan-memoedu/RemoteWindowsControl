function Set-SessionProcessLifetime {
    if ('RemoteAssistanceLifetime' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
public static class RemoteAssistanceLifetime {
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct Counters {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }
    [StructLayout(LayoutKind.Sequential)] struct Extended {
        public Basic BasicLimitInformation;
        public Counters IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    static IntPtr handle;
    public static void Attach() {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        var info = new Extended(); info.BasicLimitInformation.LimitFlags = 0x2000;
        int size = Marshal.SizeOf(typeof(Extended));
        IntPtr ptr = Marshal.AllocHGlobal(size);
        try {
            Marshal.StructureToPtr(info, ptr, false);
            if (!SetInformationJobObject(handle, 9, ptr, (uint)size)) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (!AssignProcessToJobObject(handle, Process.GetCurrentProcess().Handle)) throw new Win32Exception(Marshal.GetLastWin32Error());
        } finally { Marshal.FreeHGlobal(ptr); }
        // The non-inheritable handle closes on process exit and kills only this job's children.
    }
}
'@
    [RemoteAssistanceLifetime]::Attach()
}
