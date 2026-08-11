import { Bot, FolderKanban, GitBranch, LogOut, SlidersHorizontal, UserRound } from 'lucide-react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'

const navItems = [
  { to: '/agent', label: '主 Agent', icon: Bot },
  { to: '/projects', label: '学习项目', icon: FolderKanban },
  { to: '/memory', label: '记忆图谱', icon: GitBranch },
  { to: '/profile', label: '个人画像', icon: UserRound },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const exit = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <header className="shrink-0 border-b border-gray-200 bg-white px-3 sm:px-6">
        <div className="mx-auto flex h-16 max-w-[1480px] items-center justify-between gap-3">
          <Link to="/agent" className="flex shrink-0 items-center gap-2 text-lg font-bold text-indigo-600 sm:text-xl"><span className="text-2xl" aria-hidden>✦</span><span className="hidden sm:inline">LearnFlow</span></Link>
          <nav className="flex min-w-0 items-center gap-1" aria-label="主导航">
            {navItems.map(item => {
              const Icon = item.icon
              return <NavLink key={item.to} to={item.to} title={item.label} aria-label={item.label} className={({ isActive }) => `flex h-10 items-center gap-2 px-2.5 text-xs font-medium transition-colors rounded-lg sm:px-3 sm:text-sm ${isActive ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-950'}`}><Icon size={16} /><span className="hidden min-[430px]:inline">{item.label}</span></NavLink>
            })}
          </nav>
          <div className="flex shrink-0 items-center gap-1">
            {user?.is_dev_login && <Link to="/settings" title="开发设置" className="flex h-9 w-9 items-center justify-center text-gray-500 hover:bg-gray-100 rounded-lg"><SlidersHorizontal size={17} /></Link>}
            <span className="hidden max-w-28 truncate text-xs text-gray-500 md:block">{user?.display_name}</span>
            <button onClick={exit} title="退出登录" className="flex h-9 w-9 items-center justify-center text-gray-500 hover:bg-red-50 hover:text-red-600 rounded-lg"><LogOut size={17} /></button>
          </div>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden"><Outlet /></main>
    </div>
  )
}
