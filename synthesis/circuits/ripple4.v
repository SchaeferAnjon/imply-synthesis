module ripple4(input [3:0] a, b, input cin, output [3:0] s, output cout);
  assign {cout, s} = a + b + cin;
endmodule
