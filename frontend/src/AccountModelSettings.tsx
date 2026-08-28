/// <reference types="vite/client" />

import { useEffect, useState, type FormEvent } from 'react'

import {
  deleteFormalModelCredential,
  listFormalAdminAccounts,
  loadFormalModelCredential,
  saveFormalModelCredential,
  testFormalModelCredential,
  type FormalAccount,
  type FormalAdminAccount,
  type FormalModelCredentialMetadata,
} from './formal-runtime.ts'
import styles from './AccountModelSettings.module.css'

type AccountModelSettingsProps = {
  account: FormalAccount
  baseUrl: string
  model: string
  onConnectionChange: (patch: Partial<{ baseUrl: string; model: string }>) => void
  onSignOut: () => Promise<void>
}

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

function dateLabel(value?: string | null) {
  if (!value) return '尚未更新'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '已更新' : parsed.toLocaleString('zh-CN')
}

export default function AccountModelSettings({
  account,
  baseUrl,
  model,
  onConnectionChange,
  onSignOut,
}: AccountModelSettingsProps) {
  const [credential, setCredential] = useState<FormalModelCredentialMetadata>()
  const [adminAccounts, setAdminAccounts] = useState<FormalAdminAccount[]>([])
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(true)
  const [busyAction, setBusyAction] = useState('')
  const [deleteArmed, setDeleteArmed] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    const credentialRequest = loadFormalModelCredential()
    const accountsRequest = account.role === 'admin'
      ? listFormalAdminAccounts()
      : Promise.resolve([] as FormalAdminAccount[])
    Promise.all([credentialRequest, accountsRequest])
      .then(([metadata, accounts]) => {
        if (!active) return
        setCredential(metadata)
        setAdminAccounts(accounts)
      })
      .catch(loadError => {
        if (active) setError(messageFrom(loadError, '账号设置加载失败'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [account.learner_id, account.role])

  const refreshAdminAccounts = async () => {
    if (account.role !== 'admin') return
    setAdminAccounts(await listFormalAdminAccounts())
  }

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusyAction('save')
    setError('')
    setNotice('')
    try {
      const metadata = await saveFormalModelCredential(apiKey)
      setCredential(metadata)
      setApiKey('')
      setDeleteArmed(false)
      await refreshAdminAccounts()
      setNotice(apiKey.trim() ? '模型凭据已加密更新；输入框已清空。' : '界面配置已保存；空 Key 保留了现有凭据。')
    } catch (saveError) {
      setError(messageFrom(saveError, '模型设置保存失败'))
    } finally {
      setBusyAction('')
    }
  }

  const removeCredential = async () => {
    if (!deleteArmed) {
      setDeleteArmed(true)
      setNotice('再次点击以确认删除本人模型凭据。')
      setError('')
      return
    }
    setBusyAction('delete')
    setError('')
    setNotice('')
    try {
      setCredential(await deleteFormalModelCredential())
      setApiKey('')
      setDeleteArmed(false)
      await refreshAdminAccounts()
      setNotice('本人模型凭据已删除。')
    } catch (deleteError) {
      setError(messageFrom(deleteError, '模型凭据删除失败'))
    } finally {
      setBusyAction('')
    }
  }

  const testCredential = async () => {
    if (apiKey.trim()) {
      setError('输入框中有尚未保存的 Key；请先保存，再测试服务端已加密的凭据。')
      return
    }
    setBusyAction('test')
    setError('')
    setNotice('')
    try {
      const result = await testFormalModelCredential(baseUrl, model)
      setNotice(`连接成功：${result.model}，${result.latency_ms} ms。`)
    } catch (testError) {
      setError(messageFrom(testError, '模型凭据测试失败'))
    } finally {
      setBusyAction('')
    }
  }

  const signOut = async () => {
    setBusyAction('logout')
    setError('')
    try {
      await onSignOut()
    } catch (logoutError) {
      setError(messageFrom(logoutError, '退出登录失败'))
      setBusyAction('')
    }
  }

  return (
    <div className={styles.stack}>
      <section className={styles.card} aria-labelledby="account-settings-title">
        <div className={styles.heading}>
          <span>01</span>
          <div><h2 id="account-settings-title">账号与缓存边界</h2><p>当前浏览器工作区只写入 learner #{account.learner_id} 的 scoped key。</p></div>
          <i>{account.role === 'admin' ? '管理员' : '学习者'}</i>
        </div>
        <div className={styles.accountRow}>
          <div className={styles.avatar}>{account.display_name.slice(0, 1).toUpperCase()}</div>
          <div><strong>{account.display_name}</strong><span>@{account.username} · 账号 #{account.account_number}</span></div>
          <button type="button" className={styles.secondary} disabled={Boolean(busyAction)} onClick={() => { void signOut() }}>{busyAction === 'logout' ? '正在退出…' : '退出并切换账号'}</button>
        </div>
        {account.must_change_password ? <p className={styles.warning}>此账号被标记为需要更新密码；请尽快使用账号密码接口完成修改。</p> : null}
      </section>

      <form className={styles.card} onSubmit={save}>
        <div className={styles.heading}>
          <span>02</span>
          <div><h2>模型连接与本人凭据</h2><p>API Key 只提交到当前账号的加密存储；页面不会回显明文。</p></div>
          <i className={credential?.configured ? styles.configured : ''}>{loading ? '读取中' : credential?.configured ? 'configured' : 'not configured'}</i>
        </div>
        <div className={styles.fieldGrid}>
          <label><span>Base URL</span><input name="model_base_url" autoComplete="url" value={baseUrl} onChange={event => onConnectionChange({ baseUrl: event.target.value })} placeholder="https://api.example.com/v1" /></label>
          <label><span>模型名称</span><input name="model_name" autoComplete="off" value={model} onChange={event => onConnectionChange({ model: event.target.value })} placeholder="例如 model-name" /></label>
        </div>
        <label className={styles.keyField}>
          <span>API Key</span>
          <input name="model_api_key" type="password" value={apiKey} onChange={event => { setApiKey(event.target.value); setDeleteArmed(false) }} autoComplete="new-password" placeholder={credential?.configured ? '留空以保留现有凭据' : '输入当前账号的模型 API Key'} />
          <small>{credential?.configured ? `已配置 ${credential.key_hint || 'masked key'} · ${dateLabel(credential.updated_at)}。空输入会保留现有 Key。` : '尚未配置。明文仅存在于本次输入状态，不写入 localStorage。'}</small>
        </label>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        {notice ? <p className={styles.notice} role="status">{notice}</p> : null}
        <div className={styles.actions}>
          <button type="submit" disabled={Boolean(busyAction)}>{busyAction === 'save' ? '正在保存…' : credential?.configured ? '保存 / 更新' : '保存凭据'}</button>
          <button type="button" className={styles.secondary} disabled={Boolean(busyAction) || !credential?.configured} onClick={() => { void testCredential() }}>{busyAction === 'test' ? '正在测试…' : '测试连接'}</button>
          <button type="button" className={deleteArmed ? styles.dangerArmed : styles.danger} disabled={Boolean(busyAction) || !credential?.configured} onClick={() => { void removeCredential() }}>{busyAction === 'delete' ? '正在删除…' : deleteArmed ? '确认删除凭据' : '删除凭据'}</button>
        </div>
      </form>

      {account.role === 'admin' ? (
        <section className={styles.card} aria-labelledby="admin-account-title">
          <div className={styles.heading}>
            <span>03</span>
            <div><h2 id="admin-account-title">账号凭据配置概览</h2><p>管理员视图只展示 configured 状态，不展示其他账号的 key hint 或密文。</p></div>
            <i>{adminAccounts.length} 个账号</i>
          </div>
          <div className={styles.accountList}>
            {adminAccounts.map(item => (
              <article key={item.account_number}>
                <div><strong>{item.display_name}</strong><span>@{item.username} · {item.role} · {item.status} · {item.project_count} 个项目</span></div>
                <b className={item.api_key_configured ? styles.yes : styles.no}>{item.api_key_configured ? 'configured' : 'not configured'}</b>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
