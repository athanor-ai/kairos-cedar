permit (
    principal,
    action,
    resource is FS::Disk
)
when { resource.__cedar };
