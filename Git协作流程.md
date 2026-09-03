# Git 日常协作流程

本文摘取并整理 Desktop《Git与GitHub项目协作操作说明》的第 8～11 部分，供
`_T0` 项目成员日常开发时直接查阅。首次建立仓库、配置身份和添加远端等一次性
步骤不在本文重复说明。

## 8. 日常个人工作流程

### 8.1 开始前检查并更新主分支

```powershell
Set-Location 'C:\Users\65128\Desktop\_T0'
git status
git branch --show-current
git remote -v
```

如果有未提交修改，应先完成并提交，或临时保存：

```powershell
git stash push -u -m "WIP: market validation"
git stash list
```

恢复时先切回正确分支，再执行 `git stash pop`。`-u` 会包含未跟踪文件，恢复后
仍需检查 `git status`。工作区干净后更新主分支：

```powershell
git switch main
git pull --ff-only
```

`--ff-only` 只允许快进更新。如果本地 `main` 有远端不存在的提交，Git 会停止，
而不是自动制造合并提交。此时使用以下命令检查分叉：

```powershell
git log --oneline --graph --decorate --all -15
```

### 8.2 建立单一任务分支

```powershell
git switch -c feature/market-validation
```

推荐分支前缀：

- `feature/`：新功能；
- `fix/`：缺陷修复；
- `refactor/`：结构调整；
- `docs/`：文档修改；
- `test/`：测试补充；
- `analysis/`：分析任务。

例如 `docs/stockdb-setup` 或 `fix/lag1-date-alignment`。分支名建议使用小写英文、
数字和连字符；一个分支只处理一个主题。

### 8.3 修改、检查和测试

```powershell
git status
git diff
git diff --stat
```

修改 Python 核心模块后，至少执行：

```powershell
python -m py_compile main.py database.py schema.py market_environment.py prepare.py analysis_account.py analysis_algo.py test.py
```

涉及数据库或分析口径时，还要执行对应的数据质量检查。没有 Git 冲突不代表业务
逻辑一定正确。

### 8.4 明确暂存并复核

优先按文件添加，不要习惯性使用 `git add .`：

```powershell
git add market_environment.py test.py README.md
git diff --cached --stat
git diff --cached
git diff --cached --check
```

误暂存时执行：

```powershell
git restore --staged <文件名>
```

这只取消暂存，不删除本地修改。提交前再次确认没有数据库、真实 CSV、日志、报告、
凭据或 StockDB 本地数据。

### 8.5 提交并推送

```powershell
git commit -m "Validate market environment data"
git push -u origin feature/market-validation
```

提交信息应说明完成的动作，避免只写 `update` 或 `修改`。第一次推送使用 `-u`
建立跟踪关系，以后在同一分支直接执行 `git push`。

### 8.6 创建 Pull Request

在 GitHub 创建 Pull Request，确认 `base: main`、`compare:` 为自己的功能分支。
描述至少包含修改目的、涉及模块、数据口径是否变化、验证命令、已知限制和希望
同学重点检查的内容。

收到审查意见后，在同一功能分支继续修改、提交和推送，原 Pull Request 会自动
更新，不需要重新创建。

### 8.7 合并后清理

```powershell
git switch main
git pull --ff-only
git branch -d feature/market-validation
git fetch --prune
```

需要删除远端功能分支时：

```powershell
git push origin --delete feature/market-validation
```

如果 `git branch -d` 提示尚未合并，不要立即使用 `-D`，先确认提交是否确实已经
进入 `main`。

## 9. 同步其他同学的修改

### 9.1 `fetch` 与 `pull` 的区别

```powershell
git fetch origin
```

`fetch` 只下载远端分支和提交信息，不修改当前文件，适合先观察：

```powershell
git branch -vv
git log --oneline --graph --decorate --all -15
git diff main..origin/main
```

`pull` 会获取远端内容并更新当前分支。对 `main` 建议固定使用快进模式：

```powershell
git switch main
git pull --ff-only
```

执行前要确保工作区干净；否则先提交或 stash。

### 9.2 个人功能分支跟进最新 `main`

```powershell
git fetch origin
git switch main
git pull --ff-only
git switch feature/market-validation
git rebase main
```

也可以在 `git fetch origin` 后直接执行 `git rebase origin/main`。rebase 会把个人
提交重新应用到最新主分支之后，适合主要由自己使用的功能分支。不要随意 rebase
多人共同维护的共享分支，因为提交哈希会改变。

### 9.3 rebase 没有冲突时

重新检查并运行测试：

```powershell
git status
git log --oneline --graph --decorate -10
```

如果该分支从未推送，正常执行 `git push -u origin <分支名>`。如果 rebase 前已经
推送，普通 push 会因历史改变而被拒绝；确认是自己的分支且无人追加提交后使用：

```powershell
git push --force-with-lease
```

`--force-with-lease` 会在远端存在自己尚未获取的新提交时拒绝覆盖，比
`--force` 安全。任何情况下都不要对 `main` 强制推送。

### 9.4 识别和解决冲突

Git 暂停 rebase 后先执行 `git status`。冲突文件一般包含：

```text
[当前分支内容开始]
main 中的内容
[双方内容分隔]
个人提交中的内容
[另一提交内容结束]
```

理解双方修改意图，整理为最终正确内容，并删除全部标记。检查是否仍有遗漏：

```powershell
rg -n "^(<<<<<<<|=======|>>>>>>>)" .
```

每轮解决后：

```powershell
git add <已解决的文件1> <已解决的文件2>
git status
git rebase --continue
```

后续提交再次冲突时重复上述过程。只有确认某个完整提交已经不需要时，才使用
`git rebase --skip`；它会跳过整个提交，不能当作普通解决手段。

### 9.5 放弃本次 rebase

如果方向错误、冲突过多或暂时无法判断：

```powershell
git rebase --abort
```

这会回到 rebase 开始前，比删除文件或执行 `git reset --hard` 更安全。

### 9.6 多人共享分支使用 merge

多人共同维护同一功能分支时，为避免重写共同历史，可以合并主分支：

```powershell
git fetch origin
git switch feature/shared-analysis
git merge origin/main
```

解决冲突后执行 `git add <文件>`、`git commit`、`git push`。需要放弃未完成的
合并时执行 `git merge --abort`。团队最好约定个人分支使用 rebase、共享分支
使用 merge。

### 9.7 Pull Request 合并前终检

同步最新 `main` 后重新运行测试，并在 GitHub 确认：

- Pull Request 的 base 是 `main`；
- 自动检查或手工测试通过；
- review 对话已经解决；
- Files changed 没有无关文件或敏感数据；
- 已获得团队约定的审核。

安全原则：不对 `main` 使用 `--force`；不使用 `git reset --hard` 解决普通同步
问题；不确定冲突含义时暂停并联系原修改者。

## 10. 推荐团队约定

- `main` 只接收经过检查的 Pull Request。
- 每个分支只完成一个清晰任务。
- 提交信息说明“做了什么”，避免使用 `update`、`修改` 等模糊描述。
- 提交前运行与改动相关的测试，并检查 `git diff --cached`。
- 真实交易数据和本地数据库通过获批的内部渠道共享，不使用 GitHub。
- `.gitignore` 无法清除已经提交的敏感信息；发现误提交时立即停止推送并处理历史。

## 11. 常用状态命令

```powershell
git status
git log --oneline --graph --decorate -10
git branch -vv
git remote -v
git diff
git diff --cached
```
