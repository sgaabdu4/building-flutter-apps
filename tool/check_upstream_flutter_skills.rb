#!/usr/bin/env ruby
# frozen_string_literal: true

require 'digest'
require 'fileutils'
require 'json'
require 'open3'
require 'time'
require 'tmpdir'

DEFAULT_REPO = 'https://github.com/flutter/skills.git'
DEFAULT_BRANCH = 'main'
DEFAULT_LOCK = File.expand_path('upstream/flutter_skills.lock.json', __dir__)

def usage
  warn <<~USAGE
    Usage:
      ruby tool/check_upstream_flutter_skills.rb [--update] [--strict-commit]

    Options:
      --update          Refresh the lock file to the current upstream state.
      --strict-commit   Exit non-zero when upstream commit changes, even if skill hashes do not.
      --repo URL        Override upstream repository URL.
      --branch NAME     Override branch. Default: main.
      --lock PATH       Override lock file path.
  USAGE
end

def run!(*cmd)
  stdout, stderr, status = Open3.capture3(*cmd)
  return stdout if status.success?

  warn stderr
  abort "Command failed: #{cmd.join(' ')}"
end

def parse_args(argv)
  options = {
    update: false,
    strict_commit: false,
    repo: DEFAULT_REPO,
    branch: DEFAULT_BRANCH,
    lock_path: DEFAULT_LOCK,
  }

  until argv.empty?
    arg = argv.shift
    case arg
    when '--update'
      options[:update] = true
    when '--strict-commit'
      options[:strict_commit] = true
    when '--repo'
      options[:repo] = argv.shift
    when '--branch'
      options[:branch] = argv.shift
    when '--lock'
      options[:lock_path] = File.expand_path(argv.shift)
    when '-h', '--help'
      usage
      exit 0
    else
      usage
      abort "Unknown argument: #{arg}"
    end
  end

  options
end

def strip_quotes(value)
  return nil if value.nil?

  value.strip.sub(/\A['"]/, '').sub(/['"]\z/, '')
end

def frontmatter_value(frontmatter, key)
  match = frontmatter.match(/^#{Regexp.escape(key)}:\s*(.+)$/)
  strip_quotes(match&.[](1))
end

def nested_frontmatter_value(frontmatter, key)
  match = frontmatter.match(/^\s{2}#{Regexp.escape(key)}:\s*(.+)$/)
  strip_quotes(match&.[](1))
end

def skill_metadata(path)
  content = File.read(path)
  frontmatter = content.match(/\A---\n(.*?)\n---/m)&.[](1).to_s

  {
    name: frontmatter_value(frontmatter, 'name') || File.basename(File.dirname(path)),
    last_modified: nested_frontmatter_value(frontmatter, 'last_modified'),
    model: nested_frontmatter_value(frontmatter, 'model'),
    sha256: Digest::SHA256.hexdigest(content),
  }
end

def collect_snapshot(repo:, branch:)
  Dir.mktmpdir('flutter-skills-upstream.') do |dir|
    run!(
      'git',
      'clone',
      '--quiet',
      '--depth',
      '1',
      '--branch',
      branch,
      repo,
      dir,
    )

    commit = run!('git', '-C', dir, 'rev-parse', 'HEAD').strip
    skills = {}

    Dir.glob(File.join(dir, 'skills', '*', 'SKILL.md')).sort.each do |path|
      metadata = skill_metadata(path)
      relative_path = path.delete_prefix("#{dir}/")
      skills[metadata[:name]] = {
        'path' => relative_path,
        'sha256' => metadata[:sha256],
        'last_modified' => metadata[:last_modified],
        'model' => metadata[:model],
      }.compact
    end

    {
      'version' => 1,
      'source' => repo,
      'branch' => branch,
      'commit' => commit,
      'checked_at' => Time.now.utc.iso8601,
      'skill_count' => skills.length,
      'skills' => skills.sort.to_h,
    }
  end
end

def load_lock(path)
  return nil unless File.exist?(path)

  JSON.parse(File.read(path))
end

def write_lock(path, snapshot)
  FileUtils.mkdir_p(File.dirname(path))
  File.write(path, "#{JSON.pretty_generate(snapshot)}\n")
end

def changed_skills(old_snapshot, new_snapshot)
  old_skills = old_snapshot.fetch('skills')
  new_skills = new_snapshot.fetch('skills')
  old_names = old_skills.keys
  new_names = new_skills.keys

  changes = []

  (new_names - old_names).sort.each do |name|
    changes << ['added', name, nil, new_skills.fetch(name)]
  end

  (old_names - new_names).sort.each do |name|
    changes << ['removed', name, old_skills.fetch(name), nil]
  end

  (old_names & new_names).sort.each do |name|
    old_skill = old_skills.fetch(name)
    new_skill = new_skills.fetch(name)
    next if old_skill['sha256'] == new_skill['sha256'] &&
            old_skill['path'] == new_skill['path']

    changes << ['modified', name, old_skill, new_skill]
  end

  changes
end

def print_changes(changes)
  changes.each do |kind, name, old_skill, new_skill|
    case kind
    when 'added'
      puts "  added:    #{name} (#{new_skill['path']})"
    when 'removed'
      puts "  removed:  #{name} (#{old_skill['path']})"
    when 'modified'
      old_marker = old_skill['last_modified'] || old_skill['sha256'][0, 12]
      new_marker = new_skill['last_modified'] || new_skill['sha256'][0, 12]
      puts "  modified: #{name} (#{old_marker} -> #{new_marker})"
    end
  end
end

options = parse_args(ARGV)
snapshot = collect_snapshot(repo: options[:repo], branch: options[:branch])

if options[:update]
  write_lock(options[:lock_path], snapshot)
  puts "Updated #{options[:lock_path]}"
  puts "flutter/skills #{snapshot['branch']} @ #{snapshot['commit']}"
  puts "Tracked #{snapshot['skill_count']} Flutter skills"
  exit 0
end

lock = load_lock(options[:lock_path])
unless lock
  warn "Lock file missing: #{options[:lock_path]}"
  warn 'Run with --update to create it.'
  exit 1
end

commit_changed = lock['commit'] != snapshot['commit']
changes = changed_skills(lock, snapshot)

if commit_changed
  puts "flutter/skills #{snapshot['branch']} commit changed:"
  puts "  locked:  #{lock['commit']}"
  puts "  current: #{snapshot['commit']}"
end

if changes.empty?
  puts 'No upstream Flutter skill content changes.'
  if commit_changed
    puts 'Repo commit changed, but tracked skill hashes are unchanged.'
    exit(options[:strict_commit] ? 1 : 0)
  end
  exit 0
end

puts 'Upstream Flutter skill changes detected. Re-run the skill comparison review.'
print_changes(changes)
exit 1
