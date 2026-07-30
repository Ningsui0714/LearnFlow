import { Outlet, Link, useLocation } from 'react-router-dom'

export default function Layout() {
  const location = useLocation()
  const isActive = (path: string) => location.pathname === path

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Top nav */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between shrink-0">
        <Link to="/" className="text-xl font-bold text-primary-600 flex items-center gap-2">
          <span className="text-2xl">✦</span>
          LearnFlow
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          {location.pathname !== '/' && (
            <Link to="/" className="text-gray-500 hover:text-primary-600 transition-colors">
              项目列表
            </Link>
          )}
          <Link to="/settings" className="text-gray-400 hover:text-primary-600 text-xs transition-colors">
            ⚙️
          </Link>
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
