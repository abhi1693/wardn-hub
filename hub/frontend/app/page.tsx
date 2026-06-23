const navItems = [
  "Browse",
  "Submissions",
  "Partner Organizations",
  "Namespaces",
  "Audit",
  "Settings",
];

export default function Home() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r bg-sidebar px-4 py-5 text-sidebar-foreground md:block">
        <div className="text-sm font-semibold tracking-wide">Wardn Hub</div>
        <nav className="mt-8 space-y-1">
          {navItems.map((item) => (
            <a
              className="block rounded-md px-3 py-2 text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              href="#"
              key={item}
            >
              {item}
            </a>
          ))}
        </nav>
      </aside>
      <section className="px-4 py-5 md:ml-64 md:px-8">
        <header className="border-b pb-5">
          <p className="text-sm text-muted-foreground">MCP Registry</p>
          <h1 className="mt-1 text-2xl font-semibold">Browse servers</h1>
        </header>
        <div className="mt-6 overflow-hidden rounded-md border bg-card">
          <div className="grid grid-cols-[1fr_120px_120px] border-b bg-muted px-4 py-3 text-sm font-medium text-muted-foreground">
            <span>Name</span>
            <span>Status</span>
            <span>Latest</span>
          </div>
          <div className="flex min-h-64 items-center justify-center px-4 py-10 text-sm text-muted-foreground">
            Registry endpoints will be added in Phase 1.
          </div>
        </div>
      </section>
    </main>
  );
}

