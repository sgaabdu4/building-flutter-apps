#!/usr/bin/env ruby
# frozen_string_literal: true

markdown_files = Dir.glob(
  [
    '*.md',
    'skills/building-flutter-apps/**/*.md',
    'evals/**/*.md',
  ],
)

lint_patterns = {
  'typed local var required' => /\bvar\s+[A-Za-z_]/,
  'avoid dynamic declarations' => /\bdynamic\s+[A-Za-z_]/,
  'avoid raw List cast' => /as\s+List(?!<)/,
  'avoid raw Map cast' => /as\s+Map(?!<)/,
  'use context.mounted' => /if \(!mounted\)/,
  'widget snackbar boundary' => /SnackBarUtils\.show\w+\(/,
  'avoid shrinkWrap' => /shrinkWrap:\s*true/,
  'avoid widget build helpers' => /Widget\s+_build[A-Z]/,
  'use ref.invalidate' => /ref\.refresh\(/,
}

dart_like_text = /
  ^\s*(
    import\s+['"]package:|
    (@riverpod|@Riverpod)|
    (abstract\s+)?(base\s+|final\s+|sealed\s+)?class\s+\w+|
    void\s+\w+\(|
    Future(<[^>]+>)?\s+\w+\(|
    Widget\s+\w+\(|
    runApp\(|
    ProviderScope\(|
    ConsumerWidget|
    ListView\.|
    IconButton\(|
    onPressed:|
    ref\.|
    context\.
  )
/x

fence_counts = Hash.new(0)
expected_bad = []
unexpected_bad = []
wrong_text_fences = []

markdown_files.each do |file|
  line_number = 1
  in_fence = false
  fence_lang = nil
  start_line = nil
  block = []

  File.read(file).each_line do |line|
    if !in_fence && line.match?(/^\s*```/)
      in_fence = true
      fence_lang = line[/^\s*```([A-Za-z0-9_-]*)/, 1] || ''
      start_line = line_number
      block = []
    elsif in_fence && line.match?(/^\s*```\s*$/)
      body = block.join
      fence_counts[fence_lang] += 1

      if fence_lang == 'dart'
        lint_patterns.each do |name, regex|
          next unless body.match?(regex)

          flagged_line = body.lines.find { |body_line| body_line.match?(regex) }&.strip
          item = "#{file}:#{start_line}: #{name}: #{flagged_line}"

          if body.include?('WRONG') || body.include?('KO:')
            expected_bad << item
          else
            unexpected_bad << item
          end
        end
      elsif fence_lang == 'text' && body.match?(dart_like_text)
        flagged_line = body.lines.find { |body_line| body_line.match?(dart_like_text) }&.strip
        wrong_text_fences << "#{file}:#{start_line}: Dart-like code in text fence: #{flagged_line}"
      end

      in_fence = false
      fence_lang = nil
      start_line = nil
      block = []
    elsif in_fence
      block << line
    end

    line_number += 1
  end
end

puts "DART_FENCES=#{fence_counts['dart']}"
puts "TEXT_FENCES=#{fence_counts['text']}"
puts "EXPECTED_BAD_DART_EXAMPLES=#{expected_bad.size}"

expected_bad.each { |item| puts "EXPECTED #{item}" }

errors = unexpected_bad + wrong_text_fences
if errors.empty?
  puts 'MARKDOWN_EXAMPLES_CLEAN'
else
  errors.each { |item| warn "ERROR #{item}" }
  exit 1
end
