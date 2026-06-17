fn main() {
	let mut s = String::new();
	use std::io::Read;
	std::io::stdin().read_to_string(&mut s).unwrap();
	let mut s = s.split_whitespace();
	let white: usize = s.next().unwrap().parse().unwrap();
	let black: usize = s.next().unwrap().parse().unwrap();
	let mut field = vec![[vec!['.'; 50], vec!['#'; 50]].concat(); 43];
	for i in 0..black - 1 {
		let w = i % 24;
		let h: usize = i / 24;
		field[1 + 2 * h][1 + 2 * w] = '#';
	}
	for i in 0..white - 1 {
		let w = i % 24;
		let h: usize = i / 24;
		field[1 + 2 * h][51 + 2 * w] = '.';
	}
	println!("{} 100", field.len());
	for i in 0..field.len() {
		println!("{}", field[i].iter().collect::<String>());
	}
}
