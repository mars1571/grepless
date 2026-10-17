// @map map.core.files: the repository's files and their comment forms, what .gitignore and map.json leave out, each file's area, the tags' patterns
package mapcore

import (
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Forms are the comment forms a file writes its tags in, or nil when it carries none (data, docs, pictures).
func Forms(p string) [][2]string {
	name := p[strings.LastIndex(p, "/")+1:]
	suffix := Suffix(name)
	form, ok := CFG.Forms[suffix]
	if !ok {
		if f, ok := NAMED[name]; ok {
			form = f
		} else {
			form = EXT[suffix]
		}
	}
	if form == "" && suffix == "" && IsFile(p) {
		f, err := os.Open(filepath.Join(ROOT, p))
		if err == nil {
			b := make([]byte, 2)
			n, _ := f.Read(b)
			f.Close()
			if n == 2 && string(b) == "#!" {
				form = "hash"
			}
		}
	}
	if form == "" {
		return nil
	}
	return FORMS[form]
}

func Ignored(p string) bool {
	parts := strings.Split(p, "/")
	for _, x := range parts[:len(parts)-1] {
		if SKIP[x] {
			return true
		}
	}
	if parts[len(parts)-1] == "map.yaml" {
		return true
	}
	for _, q := range CFG.Ignore {
		t := strings.TrimRight(q, "/")
		if p == t || strings.HasPrefix(p, t+"/") || Fnmatch(p, q) {
			return true
		}
	}
	return false
}

var files_ []string
var code_ []string

func gitIgnored() []string {
	text := ReadFile(".gitignore")
	var out []string
	for _, l := range strings.Split(text, "\n") {
		l = strings.TrimSpace(l)
		if l != "" && !strings.HasPrefix(l, "#") && !strings.HasPrefix(l, "!") {
			out = append(out, l)
		}
	}
	return out
}

// RepoFiles: every file of the repository, tracked or new and not ignored when the root is a git repository's; every
// file under the root otherwise, less what .gitignore and the usual folders leave out.
func RepoFiles() []string {
	if files_ != nil {
		return files_
	}
	var found []string
	top := ""
	if b, err := exec.Command("git", "-C", ROOT, "rev-parse", "--show-toplevel").Output(); err == nil {
		top = strings.TrimSpace(string(b))
	}
	rootReal, _ := filepath.EvalSymlinks(ROOT)
	topReal, _ := filepath.EvalSymlinks(top)
	if top != "" && topReal == rootReal {
		b, _ := exec.Command("git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard", "-z").Output()
		for _, p := range strings.Split(string(b), "\x00") {
			if p == "" {
				continue
			}
			st, err := os.Lstat(filepath.Join(ROOT, p))
			if err == nil && st.Mode().IsRegular() {
				found = append(found, p)
			}
		}
	} else {
		skip := gitIgnored()
		leftOut := func(rel string, dir bool) bool {
			parts := strings.Split(rel, "/")
			for _, p := range skip {
				folder, q := strings.HasSuffix(p, "/"), strings.Trim(p, "/")
				if strings.Contains(q, "/") {
					if rel == q || strings.HasPrefix(rel, q+"/") || Fnmatch(rel, q) {
						return true
					}
				} else {
					cand := parts
					if !dir && folder {
						cand = parts[:len(parts)-1]
					}
					for _, n := range cand {
						if Fnmatch(n, q) {
							return true
						}
					}
				}
			}
			return false
		}
		var walk func(rel string)
		walk = func(rel string) {
			base := ROOT
			if rel != "." {
				base = filepath.Join(ROOT, rel)
			}
			entries, err := os.ReadDir(base)
			if err != nil {
				return
			}
			var dirs, names []string
			for _, e := range entries {
				if e.IsDir() {
					dirs = append(dirs, e.Name())
				} else {
					names = append(names, e.Name())
				}
			}
			sort.Strings(dirs)
			sort.Strings(names)
			for _, n := range names {
				p := n
				if rel != "." {
					p = rel + "/" + n
				}
				st, err := os.Lstat(filepath.Join(ROOT, p))
				if err == nil && st.Mode().IsRegular() && !leftOut(p, false) {
					found = append(found, p)
				}
			}
			for _, d := range dirs {
				p := d
				if rel != "." {
					p = rel + "/" + d
				}
				if !SKIP[d] && !leftOut(p, true) {
					walk(p)
				}
			}
		}
		walk(".")
	}
	var kept []string
	for _, p := range found {
		if !Ignored(p) {
			kept = append(kept, p)
		}
	}
	sort.Strings(kept)
	files_ = kept
	return files_
}

// Described: the [pattern, kind, about] of a file without code to read, or nil.
func Described(p string) []string {
	name := p[strings.LastIndex(p, "/")+1:]
	for _, d := range CFG.Describe {
		if Fnmatch(p, d[0]) || Fnmatch(name, d[0]) {
			return []string{d[0], d[1], d[2]}
		}
	}
	return nil
}

// Files: every file that may carry tags: a code file, not described as something else.
func Files() []string {
	if code_ != nil {
		return code_
	}
	code_ = []string{}
	for _, p := range RepoFiles() {
		if Forms(p) != nil && Described(p) == nil {
			code_ = append(code_, p)
		}
	}
	return code_
}

// AreaOf: the configured prefix, else the folder under a root, else the top folder.
func AreaOf(p string) string {
	bestPrefix, bestArea, have := "", "", false
	for _, prefix := range CFG.Areas.Keys {
		area := CFG.Areas.Str(prefix)
		q := strings.TrimRight(prefix, "/")
		if q == "" || q == "." {
			if !strings.Contains(p, "/") && !have {
				bestPrefix, bestArea, have = "", area, true
			}
		} else if (p == q || strings.HasPrefix(p, q+"/")) && (!have || len(q) > len(bestPrefix)) {
			bestPrefix, bestArea, have = q, area, true
		}
	}
	if have {
		return Slug(bestArea)
	}
	parts := strings.Split(p, "/")
	if len(parts) == 1 {
		return "root"
	}
	for _, r := range CFG.Roots {
		if parts[0] == r && len(parts) > 2 {
			return Slug(parts[1])
		}
	}
	top := strings.TrimLeft(parts[0], ".")
	if top == "" {
		top = parts[0]
	}
	return Slug(top)
}

var areas_ map[string]bool

func Areas() map[string]bool {
	if areas_ != nil {
		return areas_
	}
	areas_ = map[string]bool{}
	for _, p := range Files() {
		areas_[AreaOf(p)] = true
	}
	for _, k := range CFG.Areas.Keys {
		areas_[Slug(CFG.Areas.Str(k))] = true
	}
	for _, k := range CFG.Holds.Keys {
		areas_[k] = true
	}
	return areas_
}

type tagPat struct{ tag, looks *regexp.Regexp }

var patCache = map[string]tagPat{}

func TagPatterns(form [][2]string) tagPat {
	key := ""
	for _, f := range form {
		key += f[0] + "\x00" + f[1] + "\x01"
	}
	if p, ok := patCache[key]; ok {
		return p
	}
	var tags, looks []string
	for _, f := range form {
		tags = append(tags, `^[ \t]*`+regexp.QuoteMeta(f[0])+`[ \t]*@(map|end)[ \t]+(`+ID+`)(?::[ \t]*(.*?))?[ \t]*`+regexp.QuoteMeta(f[1])+`[ \t]*$`)
		looks = append(looks, `^[ \t]*`+regexp.QuoteMeta(f[0])+`[ \t]*@(?:map|end)\b`)
	}
	p := tagPat{regexp.MustCompile(strings.Join(tags, "|")), regexp.MustCompile(strings.Join(looks, "|"))}
	patCache[key] = p
	return p
}

// TagMatch: (kind, id, purpose) of a tag line, whichever comment form it is written in.
func TagMatch(p tagPat, line string) (string, string, string, bool) {
	m := p.tag.FindStringSubmatch(line)
	if m == nil {
		return "", "", "", false
	}
	for i := 1; i < len(m); i += 3 {
		if m[i] != "" {
			return m[i], m[i+1], strings.TrimSpace(m[i+2]), true
		}
	}
	return "", "", "", false
}

func Component(id string) string {
	parts := strings.Split(id, ".")
	if len(parts) > 2 {
		parts = parts[:2]
	}
	return strings.Join(parts, ".")
}

var testNameRx = regexp.MustCompile(`(^|[._-])(test|tests|spec)([._-]|$)`)

func IsTest(p string) bool {
	name := p[strings.LastIndex(p, "/")+1:]
	for _, g := range CFG.Tests {
		if Fnmatch(p, g) {
			return true
		}
	}
	parts := strings.Split(p, "/")
	for _, x := range parts[:len(parts)-1] {
		if x == "tests" || x == "test" || x == "spec" || x == "specs" || x == "__tests__" {
			return true
		}
	}
	stem := name
	if i := strings.LastIndex(name, "."); i >= 0 {
		stem = name[:i]
	}
	return testNameRx.MatchString(stem + ".")
}
// @end map.core.files
