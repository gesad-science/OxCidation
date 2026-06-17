use std::fmt::Write;
use std::io::*;

fn main() {
	let input = {
		let mut buf = vec![];
		stdin().read_to_end(&mut buf);
		unsafe { String::from_utf8_unchecked(buf) }
	};
	let lines = input.split('\n');

	let mut table = vec![];

	for line in lines.take(2) {
		let mut iter = line.split(' ').map(|s| s.parse::<u32>().unwrap());
		let n = iter.next().unwrap() as usize;

		table.reserve(n);

		for _ in 0..n {
			let (h, m) = (iter.next().unwrap(), iter.next().unwrap());
			table.push(h * 60 + m);
		}
	}

	table.sort();
	table.dedup();

	let mut res = String::with_capacity(5 * table.len());
	for v in table {
		write!(res, "{}:{:02} ", v / 60, v % 60);
	}
	println!("{}", res.trim_right());
}

