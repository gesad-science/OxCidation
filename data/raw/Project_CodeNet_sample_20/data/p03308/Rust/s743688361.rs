#[allow(unused_imports)] use proconio::{input, marker::{Bytes, Chars, Usize1, Isize1}};
#[allow(unused_imports)] use std::cmp::{min, max};
#[allow(unused_imports)] use superslice::Ext as _;

#[proconio::fastout]
fn main() {
	input! {
		n: usize,
		a: [isize; n],
	}

	let mut ans = 0;
	for i in 0..n-1 {
		for j in i..n {
			ans = max(ans, (a[i]-a[j]).abs());
		}
	}

	println!("{}", ans);
}
